# Test Agent Helper — Edge Platform

**Purpose:** give a fresh reviewer agent enough context to review this repository
without guessing. Read this first, then the documents linked below.

## 1. Project in one paragraph

Edge Platform is the base image and adapter kit for edge gateways. It collects
industrial telemetry (initially solar Modbus TCP), normalizes it into a frozen
`Sample` / `Batch` contract, batches and spools it, and publishes it to AWS IoT
Core through Greengrass V2. The northbound path is proven. The first southbound
slice is **Solar + Modbus TCP**, not yet implemented.

## 2. Current state

| Item | Value |
|---|---|
| Live component | `1.0.12`, RUNNING |
| LogManager | `2.3.14`, RUNNING |
| Tests | 167 |
| Remote access | Evidence-only (A); no SSH |
| Sandbox | Kept for Phase 1 |
| SNS | Confirmed |
| Heartbeat alarm | `edge-platform-sandbox-heartbeat-missing`, OK |
| Target | Solar + Modbus TCP, local surrogate first |

## 3. Repository map

| Path | What it is |
|---|---|
| `src/edge_collector/models.py` | Frozen `Sample` / `Batch` and schema version |
| `src/edge_collector/pipeline.py` | Queue, batching, flush, spool/replay |
| `src/edge_collector/spool.py` | SQLite WAL outbox |
| `src/edge_collector/config.py` | YAML config and defaults |
| `src/edge_collector/pointmap.py` | Point-map models, validation and JSON Schema |
| `src/edge_collector/sources/modbus_tcp.py` | Modbus TCP source |
| `scripts/modbus_surrogate.py` | Local solar Modbus surrogate |
| `schemas/point-map.schema.json` | Generated point-map schema |
| `config/pointmaps/` | Solar surrogate point map |
| `src/edge_collector/sources/` | Sources; only synthetic exists today |
| `src/edge_collector/sinks/` | Log, MQTT, Greengrass IPC |
| `src/edge_collector/status.py` | Heartbeat/status reporter |
| `src/edge_collector/logging_setup.py` | JSON logs, rotation, redaction |
| `src/edge_collector/support.py` | Support bundle |
| `src/edge_collector/health.py` | `/healthz`, `/readyz`, `/stats` |
| `deploy/greengrass/` | Recipe, policy and LogManager config |
| `deploy/aws/` | IoT policy, TES policy, heartbeat alarm |
| `scripts/` | Build, smoke, support upload, tunnel, alert subscription |
| `nucleus/` | Offline Greengrass nucleus image |
| `tests/` | Contract, pipeline, spool, sinks, status, logging, support, AWS drift |
| `docs/` | Handbook, decisions, runbooks and review |

## 4. Architecture

```text
source → Sample → bounded queue → batcher → sink
                                      ↘ SQLite spool (when sink unavailable)
sink → MQTT / Greengrass IPC → AWS IoT Core
```

Frozen contract:

- topics: `edge/<gateway>/<device>/telemetry`, `edge/<gateway>/status`
- quality: `good | uncertain | bad | stale`
- timestamps: UTC on the wire
- batching: `max_samples` or `flush_interval_s`
- overflow: **drop_oldest by default**, drop_newest opt-in, never block
- ordering: once anything is spooled, new batches queue behind it

## 5. Where to start reading

1. [README](README.md)
2. [Documentation Library](docs/index.html)
3. [Handbook design](docs/book/02-design.html)
4. [Solar + Modbus TCP scope](docs/solar-modbus-scope.md)
5. [Decision manifest](docs/decision-manifest.md)
6. [Environment portability](docs/environment-portability.md)
7. [Release readiness](docs/release-readiness.md)

## 6. Commands

```bash
make check        # ruff, mypy, secret guard, tests
make verify       # check + local mTLS / outage / replay
make smoke        # build and boot arm64 + x86_64 images
make component    # build Greengrass component + recipe/policy
make nucleus-smoke
```

AWS commands in the docs are examples; do not mutate AWS unless explicitly asked.
The current sandbox profile is `edge-platform-admin`, account
`632839730725`, region `ap-southeast-1`. Those are sandbox values, not client
values.

## 7. Review focus

- Data contract drift: `tests/test_schema.py`, `tests/test_models.py`
- Pipeline accounting and ordering: `tests/test_pipeline.py`
- Spool durability/budget: `tests/test_spool.py`
- Sink failure/status: `tests/test_sinks.py`, `tests/test_status.py`
- AWS artifact drift: `tests/test_aws_artifacts.py`
- Docs links: `tests/test_docs_index.py`

## 8. Known constraints

- Only the synthetic source exists. No Modbus/OPC UA/RTU.
- The test core is a 601 MB nucleus image; production base is separate.
- No inbound SSH; remote support is evidence-only.
- The SOW architecture/lakehouse/Kafka/Kubernetes/BI requirements are **not** in scope.
- Never invent a register map. Real maps need vendor documents or captured traces.
- Published component versions are immutable; bump the version.

## 9. Environment warning

Before changing a component name, account, region, bucket or thing, read
[Environment Portability](docs/environment-portability.md). The current namespace
`io.github.doudouba0309.EdgePlatform` and AWS account are sandbox placeholders.

## 10. Expected reviewer output

Report findings by severity with file/line evidence, then state whether each is:

- a code defect,
- a test gap,
- a design deviation,
- a stale document,
- or an environment/binding issue.

Do not make broad refactors during a review unless explicitly asked.
