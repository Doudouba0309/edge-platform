#!/usr/bin/env bash
# Build the collector as a Greengrass V2 component artifact.
#
# The ZIP is universal: it contains Linux wheels for arm64 and amd64, and the
# recipe has one manifest per Tier 1 architecture. This script only builds
# local files; publishing to S3 and creating the AWS component version happen
# in the deployment step.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPONENT_NAME="${GG_COMPONENT_NAME:-io.github.doudouba0309.EdgePlatform.Collector}"
COMPONENT_VERSION="${GG_COMPONENT_VERSION:-1.0.7}"
ARTIFACT_NAME="EdgeCollector-${COMPONENT_VERSION}.zip"
ARTIFACT_STEM="EdgeCollector-${COMPONENT_VERSION}"
BUCKET="${GG_BUCKET:-edge-platform-sandbox-ACCOUNT-ap-southeast-1}"
REGION="${GG_REGION:-ap-southeast-1}"
ACCOUNT_ID="${GG_ACCOUNT_ID:-123456789012}"
THING_NAME="${GG_THING_NAME:-edge-platform-sandbox-core}"
ROLE_ALIAS="${GG_ROLE_ALIAS:-edge-platform-sandbox-TESRoleAlias}"
GATEWAY_ID="${GG_GATEWAY_ID:-$THING_NAME}"
DEVICE_ID="${GG_DEVICE_ID:-plc-line-1}"
PYTHON="${PYTHON:-python3}"

BUILD_DIR="$ROOT/build/component"
PROJECT_WHEEL_DIR="$BUILD_DIR/project-wheel"
ARTIFACT_DIR="$BUILD_DIR/artifact"

fail() {
  echo "build-component: $*" >&2
  exit 1
}

command -v uv >/dev/null 2>&1 || fail "uv is required"
command -v zip >/dev/null 2>&1 || fail "zip is required"
"$PYTHON" -m pip --version >/dev/null 2>&1 \
  || fail "$PYTHON has no pip; set PYTHON to an interpreter with pip"

DIST_VERSION="$("$PYTHON" - <<'PY'
import pathlib
import tomllib
raw = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
print(tomllib.loads(raw)["project"]["version"])
PY
)"

rm -rf "$BUILD_DIR"
mkdir -p "$PROJECT_WHEEL_DIR" "$ARTIFACT_DIR/wheels"

echo "building edge-collector ${DIST_VERSION} wheel"
uv build --wheel --out-dir "$PROJECT_WHEEL_DIR" >/dev/null
cp "$PROJECT_WHEEL_DIR"/*.whl "$ARTIFACT_DIR/wheels/"

download_wheels() {
  local arch="$1" platform="$2"
  local dest="$BUILD_DIR/wheels-${arch}"
  mkdir -p "$dest"
  echo "downloading ${arch} runtime wheels"
  "$PYTHON" -m pip download \
    --dest "$dest" \
    --only-binary=:all: \
    --platform "$platform" \
    --python-version 3.12 \
    --implementation cp \
    --abi cp312 \
    "paho-mqtt>=2.1,<3" \
    "pydantic>=2.9,<3" \
    "PyYAML>=6.0,<7" \
    "awsiotsdk>=1.22,<2" >/dev/null
  cp "$dest"/*.whl "$ARTIFACT_DIR/wheels/"
}

download_wheels "arm64" "manylinux2014_aarch64"
download_wheels "amd64" "manylinux2014_x86_64"

compgen -G "$ARTIFACT_DIR/wheels/*aarch64.whl" >/dev/null \
  || fail "arm64 wheels missing"
compgen -G "$ARTIFACT_DIR/wheels/*x86_64.whl" >/dev/null \
  || fail "x86_64 wheels missing"

echo "packaging ${ARTIFACT_NAME}"
(cd "$ARTIFACT_DIR" && zip -qr "$BUILD_DIR/$ARTIFACT_NAME" .)

export COMPONENT_NAME COMPONENT_VERSION ARTIFACT_NAME ARTIFACT_STEM BUCKET
export GATEWAY_ID DEVICE_ID DIST_VERSION
export GG_REGION="$REGION" GG_ACCOUNT_ID="$ACCOUNT_ID" GG_THING_NAME="$THING_NAME" GG_ROLE_ALIAS="$ROLE_ALIAS"

"$PYTHON" - "$ROOT/deploy/greengrass/recipe.yaml.tmpl" "$BUILD_DIR/recipe.yaml" <<'PY'
import os
import pathlib
import sys

source, target = sys.argv[1], sys.argv[2]
text = pathlib.Path(source).read_text(encoding="utf-8")
values = {
    "COMPONENT_NAME": os.environ["COMPONENT_NAME"],
    "COMPONENT_VERSION": os.environ["COMPONENT_VERSION"],
    "ARTIFACT_NAME": os.environ["ARTIFACT_NAME"],
    "ARTIFACT_STEM": os.environ["ARTIFACT_STEM"],
    "BUCKET": os.environ["BUCKET"],
    "GATEWAY_ID": os.environ["GATEWAY_ID"],
    "DEVICE_ID": os.environ["DEVICE_ID"],
    "DIST_VERSION": os.environ["DIST_VERSION"],
}
for key, value in values.items():
    text = text.replace(f"__{key}__", value)
if "__" in text:
    raise SystemExit(f"unrendered placeholder in {source}")
pathlib.Path(target).write_text(text, encoding="utf-8")
PY

"$PYTHON" - "$ROOT/deploy/aws/iot-policy.json.tmpl" "$BUILD_DIR/iot-policy.json" <<'PY'
import os
import pathlib
import sys

source, target = sys.argv[1], sys.argv[2]
text = pathlib.Path(source).read_text(encoding="utf-8")
values = {
    "REGION": os.environ["GG_REGION"],
    "ACCOUNT_ID": os.environ["GG_ACCOUNT_ID"],
    "THING_NAME": os.environ["GG_THING_NAME"],
    "ROLE_ALIAS": os.environ["GG_ROLE_ALIAS"],
}
for key, value in values.items():
    text = text.replace(f"__{key}__", value)
if "__" in text:
    raise SystemExit(f"unrendered placeholder in {source}")
pathlib.Path(target).write_text(text, encoding="utf-8")
PY

echo "artifact:  $BUILD_DIR/$ARTIFACT_NAME"
echo "recipe:    $BUILD_DIR/recipe.yaml"
echo "policy:    $BUILD_DIR/iot-policy.json"
echo "wheels:    $(find "$ARTIFACT_DIR/wheels" -name '*.whl' | wc -l | tr -d ' ')"
du -h "$BUILD_DIR/$ARTIFACT_NAME" | awk '{print "size:      "$1}'
