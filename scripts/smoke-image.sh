#!/usr/bin/env bash
# Build the Tier 1 images and smoke each architecture end to end:
# boot -> ready -> schema-valid telemetry over mutual TLS -> RSS -> SIGTERM.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NETWORK="edge-platform-smoke-net"
BROKER="edge-platform-smoke-broker"
GATEWAY_ID="dev-gateway-01"  # must match config/collector-container.yaml
SMOKE_DIR="$ROOT/var/smoke-image"
PLATFORMS="${PLATFORMS:-linux/arm64 linux/amd64}"
SKIP_BUILD="${SKIP_BUILD:-0}"
CACHE_BACKEND="${CACHE_BACKEND:-}"
RSS_LIMIT_KB=153600  # 150 MiB
HOST_PORT=18081
COLLECTOR=""
SUBSCRIBER_PID=""

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cleanup() {
  local status=$?
  set +e
  if [ -n "$COLLECTOR" ]; then
    docker rm -f "$COLLECTOR" >/dev/null 2>&1
  fi
  if [ -n "$SUBSCRIBER_PID" ] && kill -0 "$SUBSCRIBER_PID" 2>/dev/null; then
    kill -TERM "$SUBSCRIBER_PID" 2>/dev/null
    wait "$SUBSCRIBER_PID" 2>/dev/null
  fi
  docker rm -f "$BROKER" >/dev/null 2>&1
  docker network rm "$NETWORK" >/dev/null 2>&1
  exit "$status"
}
trap cleanup EXIT

command -v docker >/dev/null || fail "docker is required"
command -v mosquitto_pub >/dev/null || fail "mosquitto_pub is required"
command -v curl >/dev/null || fail "curl is required"
[ -x .venv/bin/python ] || fail "create .venv with 'uv pip install -e .[dev]' first"

./scripts/gen-test-certs.sh

mkdir -p "$SMOKE_DIR" "$ROOT/var/mosquitto"
rm -f "$SMOKE_DIR"/*.jsonl "$SMOKE_DIR"/*.log
cat > "$ROOT/var/mosquitto/mosquitto.conf" <<'EOF'
listener 8883 0.0.0.0
allow_anonymous false
require_certificate true
use_identity_as_username true
cafile /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile /mosquitto/certs/server.key
log_dest stdout
EOF

wait_for_broker() {
  local i
  for i in $(seq 1 100); do
    if mosquitto_pub -h 127.0.0.1 -p 8883 \
      --cafile certs/ca.crt --cert certs/client.crt --key certs/client.key \
      -t smoke/ping -m ping >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

telemetry_count() {
  if [ -f "$1" ]; then
    grep -c '/telemetry"' "$1" || true
  else
    echo 0
  fi
}

reset_retained_status() {
  mosquitto_pub -h 127.0.0.1 -p 8883 \
    --cafile certs/ca.crt --cert certs/client.crt --key certs/client.key \
    -r -n -t "edge/${GATEWAY_ID}/status" >/dev/null 2>&1 \
    || fail "could not clear retained status"
}

docker rm -f "$BROKER" >/dev/null 2>&1 || true
docker network rm "$NETWORK" >/dev/null 2>&1 || true
docker network create "$NETWORK" >/dev/null
docker run -d --name "$BROKER" \
  --network "$NETWORK" --network-alias mosquitto \
  -p 8883:8883 \
  -v "$ROOT/var/mosquitto:/mosquitto/config:ro" \
  -v "$ROOT/certs:/mosquitto/certs:ro" \
  eclipse-mosquitto:2.0 >/dev/null

wait_for_broker || {
  docker logs "$BROKER" >&2 || true
  fail "broker did not become ready"
}

for platform in $PLATFORMS; do
  arch="${platform#linux/}"
  image="edge-platform-base:${arch}"
  capture="$SMOKE_DIR/${arch}.jsonl"
  collector_log="$SMOKE_DIR/${arch}-collector.log"

  echo "=== ${platform} ==="

  if [ "$SKIP_BUILD" != "1" ]; then
    cache_args=()
    if [ "$CACHE_BACKEND" = "gha" ]; then
      cache_args+=(--cache-from "type=gha,scope=edge-platform-base-${arch}")
      cache_args+=(--cache-to "type=gha,mode=max,scope=edge-platform-base-${arch}")
    fi
    docker buildx build --platform "$platform" --load \
      ${cache_args[@]+"${cache_args[@]}"} -t "$image" . \
      || fail "image build failed for ${platform}"
  fi
  docker image inspect "$image" >/dev/null 2>&1 \
    || fail "image ${image} is missing"
  image_arch="$(docker image inspect "$image" --format '{{.Architecture}}')"
  [ "$image_arch" = "$arch" ] \
    || fail "image ${image} is ${image_arch}, expected ${arch}"

  reset_retained_status
  : > "$capture"
  .venv/bin/python scripts/smoke_subscriber.py \
    --host 127.0.0.1 --port 8883 \
    --ca certs/ca.crt --cert certs/client.crt --key certs/client.key \
    --client-id "smoke-sub-${arch}" \
    --out "$capture" \
    > "$SMOKE_DIR/${arch}-subscriber.log" 2>&1 &
  SUBSCRIBER_PID=$!

  for i in $(seq 1 100); do
    grep -q "subscribed" "$SMOKE_DIR/${arch}-subscriber.log" 2>/dev/null && break
    sleep 0.1
  done
  grep -q "subscribed" "$SMOKE_DIR/${arch}-subscriber.log" 2>/dev/null \
    || fail "subscriber did not connect for ${arch}"

  COLLECTOR="edge-platform-smoke-collector-${arch}"
  docker rm -f "$COLLECTOR" >/dev/null 2>&1 || true
  docker run -d --name "$COLLECTOR" \
    --platform "$platform" \
    --network "$NETWORK" \
    -p "${HOST_PORT}:8081" \
    -v "$ROOT/certs:/run/edge-platform/certs:ro" \
    -v "$ROOT/config/collector-container.yaml:/etc/edge-platform/collector.yaml:ro" \
    "$image" >/dev/null

  READY=0
  for i in $(seq 1 150); do
    if ! docker inspect -f '{{.State.Running}}' "$COLLECTOR" 2>/dev/null \
      | grep -q true; then
      docker logs "$COLLECTOR" >&2 || true
      fail "collector exited before ready on ${arch}"
    fi
    if curl -sf "http://127.0.0.1:${HOST_PORT}/readyz" >/dev/null 2>&1; then
      READY=1
      break
    fi
    sleep 0.2
  done
  [ "$READY" -eq 1 ] || {
    docker logs "$COLLECTOR" >&2 || true
    fail "collector did not become ready on ${arch}"
  }

  for i in $(seq 1 100); do
    [ "$(telemetry_count "$capture")" -gt 0 ] && break
    sleep 0.2
  done
  [ "$(telemetry_count "$capture")" -gt 0 ] || {
    docker logs "$COLLECTOR" >&2 || true
    fail "no telemetry from ${arch}"
  }

  docker logs "$COLLECTOR" > "$collector_log" 2>&1

  RSS_KB="$(docker exec "$COLLECTOR" python -c \
    'data = open("/proc/1/status").read(); print(data.split("VmRSS:")[1].split()[0])')"
  [ -n "$RSS_KB" ] || fail "could not read RSS from ${arch} container"
  [ "$RSS_KB" -lt "$RSS_LIMIT_KB" ] || \
    fail "${arch} RSS ${RSS_KB} KB exceeds ${RSS_LIMIT_KB} KB"
  echo "${arch} RSS: ${RSS_KB} KB (limit ${RSS_LIMIT_KB} KB)"

  docker stop -t 10 "$COLLECTOR" >/dev/null
  EXIT_CODE="$(docker inspect -f '{{.State.ExitCode}}' "$COLLECTOR")"
  docker logs "$COLLECTOR" > "$collector_log" 2>&1
  [ "$EXIT_CODE" -eq 0 ] || {
    tail -30 "$collector_log" >&2 || true
    fail "collector exited ${EXIT_CODE} on SIGTERM (${arch})"
  }
  grep -q "mqtt: connected" "$collector_log" \
    || fail "no MQTT connection in ${arch} log"
  grep -q "mqtt: stopped" "$collector_log" \
    || fail "no clean sink stop in ${arch} log"

  for i in $(seq 1 50); do
    grep -q '"offline"' "$capture" 2>/dev/null && break
    sleep 0.1
  done
  grep -q '"offline"' "$capture" 2>/dev/null \
    || fail "no offline status after SIGTERM (${arch})"

  .venv/bin/python scripts/smoke_validate.py "$capture"

  docker rm -f "$COLLECTOR" >/dev/null
  COLLECTOR=""

  if [ -n "$SUBSCRIBER_PID" ] && kill -0 "$SUBSCRIBER_PID" 2>/dev/null; then
    kill -TERM "$SUBSCRIBER_PID" 2>/dev/null || true
    wait "$SUBSCRIBER_PID" 2>/dev/null || true
  fi
  SUBSCRIBER_PID=""

  echo "PASS: ${arch} boot, mutual TLS, schema, RSS, SIGTERM"
done

echo "PASS: ${PLATFORMS}"
