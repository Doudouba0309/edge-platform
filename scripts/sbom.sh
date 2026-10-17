#!/usr/bin/env bash
# Generate CycloneDX SBOMs for both Tier 1 images with Syft.
# Images must already exist locally; run `make smoke` first.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="${OUT_DIR:-$ROOT/var/sbom}"
SYFT_IMAGE="${SYFT_IMAGE:-anchore/syft:v1.54.1@sha256:3eb5379ba7b409c3f4069b686110527af0c47df993fa5c10d13e7cf34f49b1aa}"
IMAGES=("edge-platform-base:arm64" "edge-platform-base:amd64")

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[ -x .venv/bin/python ] || fail "create .venv with 'uv pip install -e .[dev]' first"
command -v docker >/dev/null || fail "docker is required"

mkdir -p "$OUT_DIR"
TMP="$ROOT/var/sbom-work"
rm -rf "$TMP"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

for image in "${IMAGES[@]}"; do
  arch="${image##*:}"
  docker image inspect "$image" >/dev/null 2>&1 \
    || fail "missing ${image}; run 'make smoke' first"

  echo "generating CycloneDX SBOM for ${image}"
  docker save "$image" -o "$TMP/${arch}.tar"
  output="$OUT_DIR/sbom-${arch}.cdx.json"
  docker run --rm \
    -v "$TMP:/work:ro" \
    "$SYFT_IMAGE" \
    "docker-archive:/work/${arch}.tar" -q -o cyclonedx-json \
    > "$output.tmp"
  mv "$output.tmp" "$output"

  .venv/bin/python - "$output" <<'PY'
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
