#!/usr/bin/env bash
# Offline Greengrass V2 nucleus entrypoint.
#
# 1. Create a self-signed identity on first run.
# 2. Render a nucleus config pointing at that identity.
# 3. Exec the JVM in the foreground so it is the container's main process.
#
# No AWS credentials are used. The nucleus will refuse IoT Core by design; the
# point is to exercise startup, IPC, restart and signal handling offline.
set -euo pipefail

GG_ROOT="${GG_ROOT:-/greengrass/v2}"
CERTS="${GG_ROOT}/certs"
CONFIG="/tmp/gg-config.yaml"
THING_NAME="${GG_THING_NAME:-dev-gateway-01-core}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
TES_ROLE_ALIAS="${GG_TES_ROLE_ALIAS:-edge-dev-TESRoleAlias}"
NUCLEUS_VERSION="${NUCLEUS_VERSION:-2.18.4}"

log() { printf '[nucleus] %s\n' "$*"; }

test -f /opt/gg-install/lib/Greengrass.jar || {
  log "nucleus artifact is missing"
  exit 1
}

mkdir -p "$CERTS" "$GG_ROOT/config" "$GG_ROOT/logs"

if [ ! -f "$CERTS/cert.pem" ]; then
  log "generating a self-signed identity for ${THING_NAME} (offline mode)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$CERTS/private.key" \
    -out "$CERTS/cert.pem" \
    -subj "/CN=${THING_NAME}" >/dev/null 2>&1
  chmod 600 "$CERTS/private.key"
  cp "$CERTS/cert.pem" "$CERTS/AmazonRootCA1.pem"
else
  log "reusing the existing identity in ${CERTS}"
fi

cat > "$CONFIG" <<YAML
---
system:
  certificateFilePath: "${CERTS}/cert.pem"
  privateKeyPath: "${CERTS}/private.key"
  rootCaPath: "${CERTS}/AmazonRootCA1.pem"
  rootpath: "${GG_ROOT}"
  thingName: "${THING_NAME}"
services:
  aws.greengrass.Nucleus:
    componentType: "NUCLEUS"
    version: "${NUCLEUS_VERSION}"
    configuration:
      awsRegion: "${AWS_REGION}"
      iotRoleAlias: "${TES_ROLE_ALIAS}"
      # Deliberately unroutable: there is no cloud identity, so fail fast rather
      # than hanging against a real endpoint.
      iotDataEndpoint: "localhost"
      iotCredEndpoint: "localhost"
YAML

if [ -f "$GG_ROOT/config/effectiveConfig.yaml" ]; then
  log "nucleus already installed; starting"
else
  log "installing nucleus ${NUCLEUS_VERSION} into ${GG_ROOT}"
fi

log "starting the nucleus in the foreground"
exec java \
  -Droot="$GG_ROOT" \
  -Dlog.store=FILE \
  -jar /opt/gg-install/lib/Greengrass.jar \
  --start true \
  --setup-system-service false \
  --init-config "$CONFIG" \
  --component-default-user root:root
