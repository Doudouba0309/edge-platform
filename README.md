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
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m edge_collector --config config/collector.yaml
```

Health endpoints are served on `http://127.0.0.1:8081`: `/healthz`, `/readyz`
and `/stats`. Run the tests with `.venv/bin/pytest -q`.
