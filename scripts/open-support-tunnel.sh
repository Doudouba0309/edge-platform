#!/usr/bin/env bash
# Open a short-lived AWS IoT Secure Tunneling session to a named thing.
# The core must be running aws.greengrass.SecureTunneling and an approved
# destination service (for example SSH) before the tunnel is useful.
set -euo pipefail
THING="${THING_NAME:-edge-platform-sandbox-core}"
REGION="${AWS_REGION:-ap-southeast-1}"
PROFILE="${AWS_PROFILE:-edge-platform-admin}"
DESTINATION="${TUNNEL_DESTINATION:-SSH}"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: scripts/open-support-tunnel.sh [options]
  --thing NAME           core thing (default: $THING_NAME)
  --destination SERVICE  SSH (default) or custom service
  --region REGION        AWS region
  --profile NAME         AWS profile
  --dry-run              print the request; do not open a tunnel
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --thing) THING="${2:?}"; shift 2;;
    --destination) DESTINATION="${2:?}"; shift 2;;
    --region) REGION="${2:?}"; shift 2;;
    --profile) PROFILE="${2:?}"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2;;
  esac
done

if [[ "$DRY_RUN" == "1" ]]; then
  echo "would open ${DESTINATION} tunnel to thing/${THING} in ${REGION}"
  exit 0
fi

aws iotsecuretunneling open-tunnel \
  --destination-config "thingName=${THING},services=${DESTINATION}" \
  --timeout-config maxLifetimeTimeoutMinutes=60 \
  --region "$REGION" --profile "$PROFILE"
