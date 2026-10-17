#!/usr/bin/env bash
# Generate CycloneDX SBOMs for both Tier 1 images with Syft.
# Images must already exist locally; run `make smoke` first.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="${OUT_DIR:-$ROOT/var/sbom}"
SYFT_IMAGE="${SYFT_IMAGE:-anchore/syft:v1.54.1@sha256:3eb5379ba7b409c3f4069b686110527af0c47df993fa5c10d13e7cf34f49b1aa}"
if [ "$#" -gt 0 ]; then
  IMAGES=("$@")
else
  IMAGES=("edge-platform-base:arm64" "edge-platform-base:amd64")
fi
PYTHON_BIN=".venv/bin/python"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

command -v docker >/dev/null || fail "docker is required"
command -v "$PYTHON_BIN" >/dev/null || fail "python3 is required"

mkdir -p "$OUT_DIR"
TMP="$ROOT/var/sbom-work"
rm -rf "$TMP"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

for image in "${IMAGES[@]}"; do
  arch="${image##*:}"
  label="${image%%:*}"
  label="${label##*/}"
  docker image inspect "$image" >/dev/null 2>&1 \
    || fail "missing ${image}; run the image build first"

  echo "generating CycloneDX SBOM for ${image}"
  docker save "$image" -o "$TMP/${arch}.tar"
  output="$OUT_DIR/sbom-${label}-${arch}.cdx.json"
  docker run --rm \
    -v "$TMP:/work:ro" \
    "$SYFT_IMAGE" \
    "docker-archive:/work/${arch}.tar" -q -o cyclonedx-json \
    > "$output.tmp"
  mv "$output.tmp" "$output"

  "$PYTHON_BIN" - "$output" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
if data.get("bomFormat") != "CycloneDX":
    raise SystemExit(f"{path}: not a CycloneDX document")
if not data.get("specVersion"):
    raise SystemExit(f"{path}: missing CycloneDX specVersion")
components = len(data.get("components", []))
print(f"{path}: CycloneDX {data['specVersion']}, {components} components")
PY
done

echo "SBOMs written to ${OUT_DIR}"
