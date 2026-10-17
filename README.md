# Edge Platform

This repository is the base image and adapter kit for edge gateways that collect OPC UA, Modbus, and MQTT data and publish it to AWS IoT Core via AWS IoT Greengrass V2.

Design documents live under `docs/`:

- [Edge Platform Proposal](docs/edge-platform-proposal.html)
- [Edge Platform Roadmap](docs/edge-platform-roadmap.html)
- [Open Questions and Decision Register](docs/open-questions.md)

Implementation decisions are recorded under [`docs/decisions/`](docs/decisions/).

Operational guides:

- [AWS Sandbox Setup](docs/aws-sandbox-setup.html)
- [Testing and Validation](docs/testing-validation.html)
- [Edge Platform Handbook](docs/book/index.html)
- [Phase 1+ Decision Manifest](docs/decision-manifest.md)

## Local runtime

The Phase 0 runtime skeleton runs from a YAML config with a deterministic
synthetic source:

```bash
make install
.venv/bin/python -m edge_collector --config config/collector.yaml
```

Health endpoints are served on `http://127.0.0.1:8081`: `/healthz`, `/readyz`
and `/stats`.

### Logs, status and support

The local config writes human-readable logs to stdout and to
`var/collector.log`. The container and Greengrass component configs use JSON
logs with a bounded rotating file. Gateway presence and heartbeats are
published separately from telemetry on `edge/<gateway>/status`.

Create a redacted support bundle for remote diagnosis:

```bash
.venv/bin/edge-collector-support \
  --config config/collector.yaml \
  --log-file var/collector.log \
  --output var/support-bundle.zip
```

The bundle contains the config, recent logs, system/disk information and spool
summary. Private keys and obvious secrets are redacted.

## Verification

```bash
make check    # ruff format/check + mypy --strict + secret guard + unit tests
make verify   # check + local mTLS/spool smoke (Docker, mosquitto_pub)
make smoke    # build the Tier 1 collector images and boot-smoke each
make sbom     # CycloneDX SBOMs for the collector images (after make smoke)
make nucleus-smoke  # build and verify the offline Greengrass nucleus
make sbom-nucleus   # CycloneDX SBOMs for the nucleus images
```

`make check` needs no Docker. The smoke targets expect Docker; `make verify`
also needs the host Mosquitto clients. CI runs the gates on code and image
changes to `main` and on pull requests; documentation-only changes skip that
pipeline. Image builds reuse a GitHub Actions buildx cache between runs.

`make hooks` installs the pre-commit secret guard locally. A separate security
workflow runs on every push and pull request, including documentation-only
changes, because the main pipeline's path filter deliberately skips those.

### Greengrass component

`make component` builds the collector as a Greengrass V2 component:

- a wheelhouse with Linux `arm64` and `x86_64` wheels, including the `aws`
  extra (`awsiotsdk`);
- a recipe with one explicit manifest per architecture and `NoContainer`
  execution;
- the rendered IoT policy template.

Outputs land in `build/component/` and are intentionally git-ignored. The build
needs `pip` and network access to populate the wheelhouse. See
[`docs/component-packaging.md`](docs/component-packaging.md).

## End-to-end smoke

`./scripts/smoke-local.sh` generates local test certificates, starts the
`eclipse-mosquitto:2.0` container on port `8883` with mutual TLS, runs the
collector from `config/collector-smoke.yaml`, validates a schema-conformant
telemetry batch and status message, stops the broker to force spooling,
restarts it to verify replay, checks RSS against the 150 MB ceiling and sends
SIGTERM. It requires Docker and `mosquitto_pub`; all generated material stays
under the git-ignored `certs/` and `var/` directories.

## Base image

The Tier 1 base image is built for both architectures and smoke-tested:

```bash
./scripts/smoke-image.sh
```

This builds `edge-platform-base:arm64` and `edge-platform-base:amd64` from the
pinned Ubuntu 24.04 base with runtime dependencies constrained by
`constraints.txt`, runs each container against a local mTLS Mosquitto
broker, validates telemetry, checks RSS against the 150 MB ceiling and verifies
SIGTERM. It requires Docker/buildx and `mosquitto_pub`. The container config is
[`config/collector-container.yaml`](config/collector-container.yaml); images are
local artifacts and are not published by this script.

`make sbom` scans the collector images with Syft and writes CycloneDX JSON to
`var/sbom/`; CI uploads those files as artifacts. `make sbom-nucleus` does the
same for the nucleus images.

## Greengrass nucleus (offline)

`make nucleus-smoke` builds `edge-platform-nucleus:arm64` and
`edge-platform-nucleus:amd64` from the pinned Greengrass nucleus `2.18.4`
artifact and verifies, without AWS:

- the nucleus launches and writes `Launched Nucleus successfully`;
- the IPC socket exists at `/greengrass/v2/ipc.socket`;
- a restart reuses the same self-signed identity;
- SIGTERM stops it cleanly in under 25 seconds with `--init`.

This is a separate image from the collector image because the nucleus needs a
JRE and runs as root. Composing both into the production base image is the next
packaging step.
