#!/usr/bin/env bash
# Subscribe a support address to the sandbox heartbeat alarm topic.
# Requires an explicit email address; prints a pending-subscription notice.
set -euo pipefail
EMAIL=""
PROFILE="${AWS_PROFILE:-edge-platform-admin}"
REGION="${AWS_REGION:-ap-southeast-1}"
TOPIC_NAME="${ALERT_TOPIC:-edge-platform-sandbox-alerts}"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: scripts/subscribe-alerts.sh --email ADDRESS [options]
  --email ADDRESS   support mailbox (required)
  --profile NAME    AWS profile
  --region REGION   AWS region
  --dry-run         print the request only
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) EMAIL="${2:?}"; shift 2;;
    --profile) PROFILE="${2:?}"; shift 2;;
    --region) REGION="${2:?}"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2;;
  esac
done
[[ -n "$EMAIL" ]] || { echo "--email is required" >&2; exit 2; }
TOPIC_ARN=$(aws sns list-topics --region "$REGION" --profile "$PROFILE" \
  --query "Topics[?contains(TopicArn,'${TOPIC_NAME}')].TopicArn" --output text)
[[ -n "$TOPIC_ARN" ]] || { echo "topic not found: $TOPIC_NAME" >&2; exit 2; }
if [[ "$DRY_RUN" == "1" ]]; then
  echo "would subscribe $EMAIL to $TOPIC_ARN"
  exit 0
fi
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email \
  --notification-endpoint "$EMAIL" --region "$REGION" --profile "$PROFILE"
