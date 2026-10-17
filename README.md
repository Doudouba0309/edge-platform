# Edge Platform

This repository is the base image and adapter kit for edge gateways that collect OPC UA, Modbus, and MQTT data and publish it to AWS IoT Core via AWS IoT Greengrass V2.

Design documents live under `docs/`:

- [Edge Platform Proposal](docs/edge-platform-proposal.html)
- [Edge Platform Roadmap](docs/edge-platform-roadmap.html)
- [Open Questions and Decision Register](docs/open-questions.md)

## Local runtime

The Phase 0 runtime skeleton runs from a YAML config with a deterministic
synthetic source:

```bash
make install
.venv/bin/python -m edge_collector --config config/collector.yaml
```

Health endpoints are served on `http://127.0.0.1:8081`: `/healthz`, `/readyz`
and `/stats`.

## Verification

```bash
make check    # ruff format/check + mypy --strict + unit tests
make verify   # check + local mTLS/spool smoke (Docker, mosquitto_pub)
make smoke    # build both Tier 1 images and boot-smoke each
```

`make check` needs no Docker. `make verify` and `make smoke` expect Docker and
the host Mosquitto clients. CI runs all three gates on every push to `main` and
on pull requests.

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
