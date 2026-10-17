# Greengrass component packaging

`make component` builds the collector as the Greengrass component
`io.github.doudouba0309.EdgePlatform.Collector`.

## What it produces

Everything lands in `build/component/`, which is git-ignored:

- `EdgeCollector-<version>.zip` — a universal Linux wheelhouse containing the
  collector wheel plus all runtime dependencies, including `awsiotsdk`;
- `recipe.yaml` — the rendered component recipe;
- `iot-policy.json` — the rendered IoT policy template.

The recipe has one manifest for `linux/arm64` and one for `linux/amd64`, both
pointing at the same universal artifact. The component runs in `NoContainer`
mode and publishes through the nucleus IPC; it holds no AWS credentials.

## Build inputs

Defaults are in `scripts/build-component.sh`. Override them with environment
variables for a real deployment:

```sh
GG_BUCKET=edge-platform-sandbox-<account-id>-ap-southeast-1 \
GG_ACCOUNT_ID=<account-id> \
GG_THING_NAME=edge-platform-sandbox-core \
GG_GATEWAY_ID=edge-platform-sandbox-core \
GG_DEVICE_ID=plc-line-1 \
make component
```

The artifact is built offline after the wheelhouse is populated. The component
install step creates a venv with `python3 -m venv`, so the target core needs
`python3` and `python3-venv`.

## Drift tests

`tests/test_aws_artifacts.py` reads the real recipe and policy templates and
asserts:

- the policy's `client/<thing>` grant matches the recipe's gateway/thing name;
- the policy's `edge/*` publish grant covers the collector's telemetry and
  status topics;
- the policy grants `iot:AssumeRoleWithCertificate` on the role alias and the
  Greengrass control-plane actions used by the nucleus;
- the recipe IPC `accessControl` covers the telemetry topic;
- both Tier 1 architectures are present and share the same artifact/lifecycle;
- policy topics use AWS IoT globs, not MQTT `+`/`#`.

## CI

The `component` CI job runs `make component` and uploads the ZIP, recipe and
policy as the `greengrass-component` artifact.

## Deploying

Publishing the component to S3, creating the component version, provisioning
the test core and deploying it are separate AWS steps. They are intentionally
not part of `make component`.
