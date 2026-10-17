#!/usr/bin/env bash
# Offline Greengrass nucleus smoke for both Tier 1 architectures.
# Verifies: launch, IPC socket, restart with the same identity, clean SIGTERM.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PLATFORMS="${PLATFORMS:-linux/arm64 linux/amd64}"
SKIP_BUILD="${SKIP_BUILD:-0}"
CACHE_BACKEND="${CACHE_BACKEND:-}"
CONTAINER=""
VOLUME=""

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cleanup() {
  local status=$?
  set +e
  if [ -n "$CONTAINER" ]; then
    docker rm -f "$CONTAINER" >/dev/null 2>&1
  fi
  if [ -n "$VOLUME" ]; then
    docker volume rm "$VOLUME" >/dev/null 2>&1
  fi
  exit "$status"
}
trap cleanup EXIT

command -v docker >/dev/null || fail "docker is required"

launch_count() {
  docker logs "$CONTAINER" 2>&1 | grep -c "Launched Nucleus successfully" || true
}

wait_for_launch() {
  local want="$1"
  local i count
  for i in $(seq 1 90); do
    if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
      docker logs "$CONTAINER" >&2 || true
      return 1
    fi
    count="$(launch_count)"
    if [ "${count:-0}" -ge "$want" ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_for_socket() {
  local i
  for i in $(seq 1 60); do
    if docker exec "$CONTAINER" test -S /greengrass/v2/ipc.socket 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

for platform in $PLATFORMS; do
  arch="${platform#linux/}"
  image="edge-platform-nucleus:${arch}"
  CONTAINER="edge-platform-nucleus-${arch}"
  VOLUME="edge-platform-nucleus-${arch}-root"

  echo "=== ${platform} ==="

  if [ "$SKIP_BUILD" != "1" ]; then
    cache_args=()
    if [ "$CACHE_BACKEND" = "gha" ]; then
      cache_args+=(--cache-from "type=gha,scope=edge-platform-nucleus-${arch}")
      cache_args+=(--cache-to "type=gha,mode=max,scope=edge-platform-nucleus-${arch}")
    fi
    docker buildx build --platform "$platform" --load \
      ${cache_args[@]+"${cache_args[@]}"} \
      -f nucleus/Dockerfile -t "$image" . \
      || fail "nucleus image build failed for ${platform}"
  fi
  docker image inspect "$image" >/dev/null 2>&1 \
    || fail "image ${image} is missing"

  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  docker volume create "$VOLUME" >/dev/null

  docker run -d --init --name "$CONTAINER" --platform "$platform" \
    -v "$VOLUME:/greengrass/v2" "$image" >/dev/null

  wait_for_launch 1 || {
    docker logs "$CONTAINER" >&2 || true
    fail "nucleus did not launch on ${arch}"
  }
  wait_for_socket || {
    docker logs "$CONTAINER" >&2 || true
    fail "nucleus IPC socket did not appear on ${arch}"
  }

  pid1="$(docker exec "$CONTAINER" ps -o comm= -p 1 | tr -d ' ')"
  [ "$pid1" = "docker-init" ] \
    || fail "${arch} PID 1 is '${pid1}', expected docker-init (--init)"

  fingerprint_before="$(docker exec "$CONTAINER" sha256sum /greengrass/v2/certs/cert.pem | awk '{print $1}')"
  [ -n "$fingerprint_before" ] || fail "no identity certificate on ${arch}"

  docker restart "$CONTAINER" >/dev/null
  wait_for_launch 2 || {
    docker logs "$CONTAINER" >&2 || true
    fail "nucleus did not relaunch on ${arch}"
  }
  wait_for_socket || {
    docker logs "$CONTAINER" >&2 || true
    fail "nucleus IPC socket did not return on ${arch}"
  }

  fingerprint_after="$(docker exec "$CONTAINER" sha256sum /greengrass/v2/certs/cert.pem | awk '{print $1}')"
  [ "$fingerprint_before" = "$fingerprint_after" ] \
    || fail "nucleus regenerated its identity on ${arch} restart"

  started="$(date +%s)"
  docker stop -t 30 "$CONTAINER" >/dev/null
  elapsed=$(( $(date +%s) - started ))
  exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$CONTAINER")"
  [ "$exit_code" -eq 0 ] || [ "$exit_code" -eq 143 ] \
    || fail "nucleus exit ${exit_code} on SIGTERM (${arch})"
  [ "$elapsed" -lt 25 ] \
    || fail "nucleus shutdown took ${elapsed}s on ${arch}; check --init"

  docker rm -f "$CONTAINER" >/dev/null
  CONTAINER=""
  docker volume rm "$VOLUME" >/dev/null
  VOLUME=""

  echo "PASS: ${arch} nucleus launch, IPC, identity reuse, SIGTERM (${elapsed}s)"
done

echo "PASS: ${PLATFORMS}"
