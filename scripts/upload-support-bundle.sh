#!/usr/bin/env bash
# Upload a redacted support bundle to the sandbox support prefix and print a
# short-lived presigned URL. Non-destructive; supports --dry-run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE=""
BUCKET="${S3_BUCKET:-}"
PREFIX="${SUPPORT_PREFIX:-support}"
PROFILE="${AWS_PROFILE:-edge-platform-admin}"
REGION="${AWS_REGION:-ap-southeast-1}"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: scripts/upload-support-bundle.sh --bundle PATH [options]
  --bundle PATH     support bundle ZIP (required)
  --bucket NAME     S3 bucket (default: $S3_BUCKET)
  --prefix PREFIX   key prefix (default: support)
  --profile NAME    AWS profile (default: $AWS_PROFILE)
  --region REGION   AWS region (default: $AWS_REGION)
  --dry-run         print the key; do not upload
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) BUNDLE="${2:?}"; shift 2;;
    --bucket) BUCKET="${2:?}"; shift 2;;
    --prefix) PREFIX="${2:?}"; shift 2;;
    --profile) PROFILE="${2:?}"; shift 2;;
    --region) REGION="${2:?}"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2;;
  esac
done

[[ -n "$BUNDLE" && -f "$BUNDLE" ]] || { echo "--bundle must be an existing file" >&2; exit 2; }
[[ -n "$BUCKET" ]] || { echo "set --bucket or S3_BUCKET" >&2; exit 2; }

KEY="${PREFIX}/$(basename "$BUNDLE")"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "would upload $BUNDLE to s3://$BUCKET/$KEY"
  exit 0
fi

aws s3 cp "$BUNDLE" "s3://$BUCKET/$KEY" --profile "$PROFILE" --region "$REGION"
aws s3 presign "s3://$BUCKET/$KEY" --expires-in 604800 --profile "$PROFILE" --region "$REGION"
