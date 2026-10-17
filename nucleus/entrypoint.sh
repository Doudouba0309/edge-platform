#!/usr/bin/env bash
# Greengrass V2 nucleus entrypoint.
#
# GG_MODE=offline (default): create a self-signed identity and point the nucleus
# at unroutable endpoints. Exercises startup, IPC, restart and signals offline.
#
# GG_MODE=aws: use the certificate/key/CA mounted at GG_CERT_DIR and connect to
# a real AWS IoT Core endpoint. Used by the sandbox proof.
set -euo pipefail

GG_ROOT="${GG_ROOT:-/greengrass/v2}"
MODE="${GG_MODE:-offline}"
CONFIG="/tmp/gg-config.yaml"
THING_NAME="${GG_THING_NAME:-dev-gateway-01-core}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
TES_ROLE_ALIAS="${GG_TES_ROLE_ALIAS:-edge-dev-TESRoleAlias}"
NUCLEUS_VERSION="${NUCLEUS_VERSION:-2.18.4}"

if [ "$MODE" = "aws" ]; then
  CERTS="${GG_CERT_DIR:-/certs}"
else
  CERTS="${GG_ROOT}/certs"
fi

log() { printf '[nucleus] %s\n' "$*"; }

test -f /opt/gg-install/lib/Greengrass.jar || {
  log "nucleus artifact is missing"
  exit 1
}

mkdir -p "$GG_ROOT/config" "$GG_ROOT/logs"

if [ "$MODE" = "aws" ]; then
  : "${GG_IOT_DATA_ENDPOINT:?GG_IOT_DATA_ENDPOINT is required in aws mode}"
  : "${GG_IOT_CRED_ENDPOINT:?GG_IOT_CRED_ENDPOINT is required in aws mode}"
  for file in cert.pem private.key AmazonRootCA1.pem; do
    test -f "${CERTS}/${file}" || {
      log "missing ${CERTS}/${file}"
      exit 1
    }
  done
  log "using the AWS identity for ${THING_NAME} from ${CERTS}"
else
  mkdir -p "$CERTS"
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
fi

if [ "$MODE" = "aws" ]; then
  ENDPOINTS="      iotDataEndpoint: \"${GG_IOT_DATA_ENDPOINT}\"\n      iotCredEndpoint: \"${GG_IOT_CRED_ENDPOINT}\""
else
  # Deliberately unroutable: there is no cloud identity, so fail fast rather
  # than hanging against a real endpoint.
  ENDPOINTS='      iotDataEndpoint: "localhost"\n      iotCredEndpoint: "localhost"'
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
$(printf '%b\n' "$ENDPOINTS")
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
