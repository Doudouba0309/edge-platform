#!/usr/bin/env bash
# End-to-end local smoke: mutual TLS, schema-valid telemetry, broker outage,
# spool replay, RSS ceiling and graceful SIGTERM. Non-interactive and re-runnable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTAINER="edge-platform-smoke-mosquitto"
SMOKE_DIR="$ROOT/var/smoke"
COLLECTOR_PID=""
SUBSCRIBER_PID=""
RSS_LIMIT_KB=153600  # 150 MiB

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cleanup() {
  local status=$?
  set +e
  if [ -n "${COLLECTOR_PID}" ] && kill -0 "${COLLECTOR_PID}" 2>/dev/null; then
    kill -TERM "${COLLECTOR_PID}" 2>/dev/null
    wait "${COLLECTOR_PID}" 2>/dev/null
  fi
  if [ -n "${SUBSCRIBER_PID}" ] && kill -0 "${SUBSCRIBER_PID}" 2>/dev/null; then
    kill -TERM "${SUBSCRIBER_PID}" 2>/dev/null
    wait "${SUBSCRIBER_PID}" 2>/dev/null
  fi
  docker rm -f "$CONTAINER" >/dev/null 2>&1
  exit "$status"
}
trap cleanup EXIT

command -v docker >/dev/null || fail "docker is required"
command -v mosquitto_pub >/dev/null || fail "mosquitto_pub is required"
command -v curl >/dev/null || fail "curl is required"

./scripts/gen-test-certs.sh

mkdir -p "$SMOKE_DIR" "$ROOT/var/mosquitto"
rm -f "$SMOKE_DIR"/*.jsonl "$SMOKE_DIR"/*.log
rm -f "$ROOT/var/spool.sqlite3" "$ROOT/var/spool.sqlite3-wal" \
  "$ROOT/var/spool.sqlite3-shm"

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
  if [ -f "$SMOKE_DIR/telemetry.jsonl" ]; then
    grep -c '/telemetry"' "$SMOKE_DIR/telemetry.jsonl" || true
  else
    echo 0
  fi
}

stats_tuple() {
  curl -sf http://127.0.0.1:8081/stats | .venv/bin/python -c \
    'import json,sys; s=json.load(sys.stdin); print(s["spooled"], s["replayed"], s["spool_pending"])'
}

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  -p 8883:8883 \
  -v "$ROOT/var/mosquitto:/mosquitto/config:ro" \
  -v "$ROOT/certs:/mosquitto/certs:ro" \
  eclipse-mosquitto:2.0 >/dev/null

wait_for_broker || {
  docker logs "$CONTAINER" >&2 || true
  fail "broker did not become ready"
}

.venv/bin/python scripts/smoke_subscriber.py \
  --host 127.0.0.1 --port 8883 \
  --ca certs/ca.crt --cert certs/client.crt --key certs/client.key \
  --client-id edge-platform-smoke-subscriber \
  --out "$SMOKE_DIR/telemetry.jsonl" \
  > "$SMOKE_DIR/subscriber.log" 2>&1 &
SUBSCRIBER_PID=$!

for i in $(seq 1 100); do
  grep -q "subscribed" "$SMOKE_DIR/subscriber.log" 2>/dev/null && break
  sleep 0.1
done
grep -q "subscribed" "$SMOKE_DIR/subscriber.log" 2>/dev/null \
  || fail "subscriber did not connect"

.venv/bin/python -m edge_collector --config config/collector-smoke.yaml \
  > "$SMOKE_DIR/collector.log" 2>&1 &
COLLECTOR_PID=$!

READY=0
for i in $(seq 1 100); do
  if ! kill -0 "$COLLECTOR_PID" 2>/dev/null; then
    tail -30 "$SMOKE_DIR/collector.log" >&2 || true
    fail "collector exited before becoming ready"
  fi
  if curl -sf http://127.0.0.1:8081/readyz >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.2
done
[ "$READY" -eq 1 ] || {
  tail -30 "$SMOKE_DIR/collector.log" >&2 || true
  fail "collector did not become ready"
}

for i in $(seq 1 100); do
  [ "$(telemetry_count)" -gt 0 ] && break
  sleep 0.2
done
[ "$(telemetry_count)" -gt 0 ] || {
  tail -30 "$SMOKE_DIR/collector.log" >&2 || true
  fail "no telemetry arrived"
}

for i in $(seq 1 50); do
  grep -q '/status"' "$SMOKE_DIR/telemetry.jsonl" 2>/dev/null && break
  sleep 0.1
done

.venv/bin/python scripts/smoke_validate.py "$SMOKE_DIR/telemetry.jsonl"

RSS_KB="$(ps -o rss= -p "$COLLECTOR_PID" | awk '{print $1}')"
[ -n "$RSS_KB" ] || fail "could not read collector RSS"
[ "$RSS_KB" -lt "$RSS_LIMIT_KB" ] || \
  fail "collector RSS ${RSS_KB} KB exceeds ${RSS_LIMIT_KB} KB"
echo "collector RSS: ${RSS_KB} KB (limit ${RSS_LIMIT_KB} KB)"

BEFORE="$(telemetry_count)"
echo "broker outage: stopping ${CONTAINER}"
docker stop "$CONTAINER" >/dev/null

SPOOLED=0
REPLAYED=0
PENDING=1
for i in $(seq 1 150); do
  read -r SPOOLED REPLAYED PENDING < <(stats_tuple) || true
  [ "${SPOOLED:-0}" -gt 0 ] && break
  sleep 0.2
done
[ "${SPOOLED:-0}" -gt 0 ] || {
  tail -30 "$SMOKE_DIR/collector.log" >&2 || true
  fail "collector did not spool while the broker was down"
}
echo "spooled while offline: ${SPOOLED} batch(es)"

echo "broker restart: starting ${CONTAINER}"
docker start "$CONTAINER" >/dev/null
wait_for_broker || fail "broker did not come back"

REPLAYED=0
PENDING=1
for i in $(seq 1 150); do
  read -r SPOOLED REPLAYED PENDING < <(stats_tuple) || true
  CURRENT="$(telemetry_count)"
  if [ "${REPLAYED:-0}" -gt 0 ] && [ "${PENDING:-1}" -eq 0 ] \
    && [ "$CURRENT" -gt "$BEFORE" ]; then
    break
  fi
  sleep 0.2
done

[ "${REPLAYED:-0}" -gt 0 ] || {
  tail -30 "$SMOKE_DIR/collector.log" >&2 || true
  fail "spooled batches were not replayed"
}
[ "$(telemetry_count)" -gt "$BEFORE" ] || fail "subscriber saw no replayed telemetry"
[ "${PENDING:-1}" -eq 0 ] || fail "spool still has pending batches"

.venv/bin/python scripts/smoke_validate.py "$SMOKE_DIR/telemetry.jsonl"

kill -TERM "$COLLECTOR_PID"
set +e
wait "$COLLECTOR_PID"
COLLECTOR_EXIT=$?
set -e
COLLECTOR_PID=""

[ "$COLLECTOR_EXIT" -eq 0 ] || {
  tail -30 "$SMOKE_DIR/collector.log" >&2 || true
  fail "collector exited ${COLLECTOR_EXIT} on SIGTERM"
}
grep -q "mqtt: stopped" "$SMOKE_DIR/collector.log" \
  || fail "collector did not stop the sink cleanly"
grep -q "replayed" "$SMOKE_DIR/collector.log" \
  || fail "collector log has no replay"

if [ -n "$SUBSCRIBER_PID" ] && kill -0 "$SUBSCRIBER_PID" 2>/dev/null; then
  kill -TERM "$SUBSCRIBER_PID" 2>/dev/null || true
  wait "$SUBSCRIBER_PID" 2>/dev/null || true
  SUBSCRIBER_PID=""
fi

echo "PASS: mutual TLS telemetry, schema, outage, replay, RSS ${RSS_KB} KB, SIGTERM"
