# Deep Review — 18 October 2026

> **Resolution update (later 18 October):** R-01, R-02, R-04, R-06, R-08, R-10,
> R-11, R-12, R-13 and R-14 were fixed and validated. R-03 now has live
> CloudWatch log shipping plus support-upload and tunnel scripts; R-05 has a
> live heartbeat metric/alarm; R-07 is an accepted test-core trade-off with a
> separate production target; R-09 is the only intentionally unexecuted
> destructive action. See the latest section at the end of this report.

- **Scope:** current `main` at `bce4127`, component `1.0.7`, live AWS sandbox, 141 tests.
- **Method:** source review, test review, live AWS inspection, documentation cross-check, targeted probes for redaction/status/versions.
- **Verdict:** the northbound core is strong and I found no data-loss defect in the pipeline or spool. The main risks are in the supportability layer, reproducibility, and documentation drift.

## Severity summary

| Severity | Count | Meaning |
|---|---:|---|
| Critical | 0 | No evidence of silent loss or a compromised credential. |
| High | 3 | Security redaction, wrong version identity, incomplete remote support for v1. |
| Medium | 7 | Status duplication, stale-online risk, unpinned wheelhouse, image size, stale docs, AWS leftovers, test gaps. |
| Low | 5 | Client-id warning, status failure counters, decision-record gap, bundle memory, support-bundle upload path. |

## Findings

### R-01 — High — Authorization tokens can survive redaction

**Evidence:** `edge_collector.logging_setup.redact`:

```
Authorization: Bearer abc123
→ Authorization: [REDACTED] abc123
```

The regex stops at whitespace after `Bearer`, so the actual token is left in the
line. `Proxy-Authorization: Basic …` has the same problem, and `api_key=…` is not
matched at all.

**Impact:** logs and the support bundle are explicitly evidence sent to a remote
support engineer. A component or library that logs an Authorization header can
leak a bearer token across borders.

**Fix:** redact the entire header value for `Authorization`, `Proxy-Authorization`
and `Bearer <token>`; add `api_key`, `apikey`, `client_secret` and common cloud
keys. Add tests with real-looking values. Prefer never logging headers at all.

### R-02 — High — Status/logs/support bundle report package 0.1.0, not component 1.0.7

**Evidence:** live heartbeat:

```json
{"version":"0.1.0","gateway_id":"edge-platform-sandbox-core",...}
```

The live Greengrass component is **1.0.7**. The same `0.1.0` appears in
`support-bundle/manifest.json` and as `service_version` in every JSON log line.

**Cause:** `collector_version()` and `support._version()` read the Python package
metadata (`edge-collector==0.1.0`). The Greengrass component version is a separate
concept and is never passed into the process.

**Impact:** a remote engineer cannot correlate a log or support bundle with the
deployed component. A rollback decision could be made against the wrong version.

**Fix:** pass `GG_COMPONENT_VERSION` through the recipe (or a
`component_version` config field) and include both `component_version` and
`package_version` in logs, status and the support manifest. Add a test.

### R-03 — High for v1 — Remote support is still incomplete

**Evidence:** structured logs, local support bundle and status heartbeat exist.
There is no CloudWatch log manager, no log upload, no support-bundle upload and
no remote tunnel. The handbook and decision manifest describe these as v1 work,
not implemented features.

**Impact:** for a client in another country, the current fallback is still
“ask the client to run a command and send a ZIP”. That is better than nothing,
but it is not a reliable remote support path, and it is unavailable if the
gateway is unreachable.

**Fix:** add the CloudWatch log manager, a presigned support-bundle upload, and an
opt-in outbound tunnel. Treat those as v1 exit criteria, not later polish.

### R-04 — Medium — MQTT status is published twice, in two formats

**Evidence:** `var/smoke-image/arm64.jsonl` contains four status records for one
lifecycle:

1. plain `"online"` from `PahoSink._on_connect`;
2. JSON `online` from `StatusReporter`;
3. JSON `offline` from `StatusReporter`;
4. plain `"offline"` from `MqttSink.stop`.

**Impact:** consumers must parse two formats. The retained last status can be the
plain string, so a JSON-only dashboard may show a stale or missing status. The
duplicate also confuses validation counts.

**Fix:** make `StatusReporter` the single owner of status. Remove the automatic
plain online/offline from `PahoSink`/`MqttSink`, or make both use the same JSON
and have only one publisher. Add a test that asserts exactly one online and one
offline per lifecycle.

### R-05 — Medium — A hard crash can leave a stale “online” status

**Evidence:** Greengrass IPC has no Last Will equivalent. `StatusReporter`
publishes `offline` only on graceful stop. If the component is killed or crashes,
the last heartbeat remains `online` until a human notices the silence.

There is no cloud-side heartbeat-expiry alarm or freshness check in the current
deployment.

**Impact:** a remote operator may believe a dead gateway is healthy.

**Fix:** alarm when no heartbeat arrives for N intervals; include `last_seen` and
a heartbeat sequence; optionally use the MQTT retained LWT when the direct MQTT
path is used. Add a documented “stale after 90s” rule.

### R-06 — Medium — Component wheelhouse is not reproducible

**Evidence:** `pyproject.toml` uses ranges (`awsiotsdk>=1.22,<2`,
`pydantic>=2.9,<3`), and `scripts/build-component.sh` downloads the latest
compatible wheels at build time. There is no component lockfile or hash pinning.
The 1.0.7 wheelhouse currently contains:

- `pydantic 2.14.1`, `pydantic_core 2.50.1`
- `awsiotsdk 1.31.0`, `awscrt 0.36.1`
- `PyYAML 6.0.3`, `paho-mqtt 2.1.0`

A future rebuild could select different versions even with the same source.

**Impact:** a rebuilt component is not provably the same artifact. This conflicts
with the “immutable version” discipline and makes a field rollback harder.

**Fix:** add a component constraints/lock file and hash verification; build from
it; test the exact wheelhouse. The image already uses `constraints.txt`; the
component should have an equivalent.

### R-07 — Medium — Nucleus image is 601 MB, above the ~400 MB target

**Evidence:** local `edge-platform-nucleus:aws-arm64` is 601 MB (the offline
arm64 image is 541 MB; amd64 517 MB). The design target is around 400 MB.

**Cause:** Ubuntu + OpenJDK 17 + nucleus + Python 3.12/venv. Python was added so
the component can create its venv.

**Impact:** slower deployment, larger storage, more update bandwidth. It is a
test-core image, not yet the final composed base, but it is a real deviation.

**Fix:** decide whether Python belongs in the final base image or whether the
component must ship a runtime; trim packages; compose the production base
deliberately.

### R-08 — Medium — Stale documentation

| Document | Stale claim | Current reality |
|---|---|---|
| `docs/aws-sandbox-setup.html` | “Published 1.0.4”, “1.0.4 is running” (lines 680, 690) | 1.0.7 is live. |
| `docs/book/03-built.html` | “21-step build history”; proof says 1.0.4 | 25 commits; 1.0.7 live. |
| `docs/book/05-rebuild-aws.html` | “The proof ended at 1.0.4” | 1.0.7 is the current proof. |
| `docs/book/appendix.html` | “latest code commit 5c24f98”; 21 commits | `bce4127`; 25 commits. |
| `docs/book/03-built.html` | AWS proof section omits the supportability slice | 1.0.7 includes logs/status/support bundle. |

The validation manual and the main handbook status page are current; these are
the remaining stale spots.

### R-09 — Medium — Live AWS cleanup is incomplete

**Evidence:** 14 deployments on the test thing (one `COMPLETED`, thirteen
`INACTIVE`), multiple component versions `1.0.0`–`1.0.7`, old S3 objects,
observer certificate, core certificate/role, and the local core container.

**Impact:** cost and drift. The current `1.0.7` proof is valid, but the account
is no longer a clean baseline.

**Fix:** confirm teardown, then run a scripted, tagged cleanup. Keep only what is
needed for the next experiment.

### R-10 — Low/Medium — `MqttSink` can use a client id different from the thing name

**Evidence:** `client_id` defaults to `gateway_id` but can be set to anything.
For direct IoT Core, the policy binds `client/<thing>`; a different client id
fails with a cryptic “not authorized”. This is not a Greengrass-path issue.

**Fix:** add an `iotcore` mode that enforces `client_id == gateway_id`, or a
warning when the host looks like an AWS IoT endpoint and they differ. Keep the
generic MQTT sink flexible for local brokers.

### R-11 — Low — Test gaps in the supportability layer

Missing tests:

- redaction of `Authorization`/`Bearer` and API keys;
- exactly one status online/offline per lifecycle;
- component version in logs/status/support manifest;
- status heartbeat expiry/staleness policy;
- support CLI `main` and its output path;
- log file open failure and backup-count rotation;
- separate status IPC policy IDs are actually distinct.

Existing tests are strong for the data contract, pipeline, spool and sink
failure paths. The gaps are concentrated in the new layer.

### R-12 — Low — Status publish failures are not counted

`PahoSink.publish_status` logs at debug and returns; `StatusReporter` logs a
warning. There is no `status_failures` counter in `/stats`, so a remote monitor
cannot distinguish “heartbeat not sent” from “heartbeat sent and lost”.

**Fix:** add a small status counter and expose it in `/stats`; increment on
publish failure and on reconnect.

### R-13 — Low — No decision record for the supportability layer

The design has `0001` (namespace/NoContainer/nucleus) and `0002` (runtime
baseline), but no `0003` for:

- no inbound SSH by default;
- outbound-only remote access;
- log retention/redaction;
- support-bundle contents;
- component-version identity.

The decision manifest captures the questions, but the accepted answers should
become a decision record.

### R-14 — Low — Support bundle reads the whole log before truncating

`support._tail_text` calls `read_bytes()` and then slices the last 1 MB. The
current log is capped at 10 MB, so this is bounded, but on a constrained device
it is still an avoidable memory spike.

**Fix:** seek to `max(0, size - max_bytes)` before reading, or stream the tail.

## What is solid

- The frozen `Sample`/`Batch` contract and schema are consistent and tested.
- The bounded queue, batching, per-device split and drop policies are covered.
- The spool is FIFO, crash-safe WAL, payload-byte budgeted and tested for
  overflow, corruption and reopen.
- The mTLS MQTT path, outage, replay and SIGTERM behaviour pass repeatedly.
- Tier 1 arm64 + x86_64 images boot and publish.
- The Greengrass component is force-reinstalled correctly, uses a universal
  wheelhouse, has explicit `aarch64`/`amd64` manifests, and the 1.0.7 status
  policy is split and working.
- The secret guard, pre-commit hook and security workflow are effective; they
  caught the test-fixture PEM literals during this work.
- The live 1.0.7 component publishes both telemetry and JSON status in AWS.

## What is deliberately not done

- Point-map contract and validator.
- Modbus TCP / RTU / OPC UA sources.
- Surrogates and conformance reports.
- CloudWatch log shipping and remote tunnel.
- Watchdog/systemd, NTP and production base composition.
- Repeatable AWS provision/publish/deploy/teardown scripts.

These are roadmap items, not regressions.

## Recommended fix order

1. **R-01 redaction** — a support bundle must not carry bearer tokens.
2. **R-02 component version identity** — make logs/status/support truthful.
3. **R-04 single status publisher** and **R-05 heartbeat freshness alarm**.
4. **R-06 wheelhouse lock** — reproducible component artifacts.
5. **R-08 stale docs** — correct the current version/status claims.
6. **R-09 cleanup** — decide teardown and script it.
7. **R-03 remote support** — CloudWatch + upload + tunnel before v1.
8. **R-07 image size** — compose/trim the production base deliberately.
9. **R-10–R-14** — small hardening.

## Bottom line

The core data path is in good shape: I would trust it for a controlled pilot.
The supportability layer is useful but not yet safe/complete for a remote client:
the version is misleading, a bearer token can leak, status is duplicated and can
go stale, and the component build is not reproducible.

No production claim is justified until R-01, R-02, R-03 and R-05 are addressed.


## Resolution update — 18 October

| Finding | Status | Evidence |
|---|---|---|
| R-01 redaction | **Fixed** | Authorization/Proxy-Authorization/Bearer/API-key probes now redact the full value; tests added. |
| R-02 version identity | **Fixed** | Live 1.0.10 status reports `version: 1.0.10` and `package_version: 0.1.0`; logs and support manifest carry component version. |
| R-03 remote support | **Mostly fixed** | LogManager 2.3.14 ships collector/system logs to CloudWatch; upload and tunnel scripts documented. A shell is still not exposed by default. |
| R-04 duplicate status | **Fixed** | Image smoke now has exactly 2 JSON status records (online/offline), one owner. |
| R-05 stale online | **Fixed** | Heartbeats carry expiry; CloudWatch metric filter and 5-minute alarm `edge-platform-sandbox-heartbeat-missing` are live. |
| R-06 wheelhouse | **Fixed** | `deploy/greengrass/component-requirements.lock` pins versions and SHA-256 hashes; build uses `--require-hashes`. |
| R-07 image size | **Accepted trade-off** | 601 MB test core accepted in `0004-image-size.md`; production base still targets ~400 MB. |
| R-08 stale docs | **Fixed** | Current references updated to 1.0.10/147 tests; historical 1.0.4 proof labeled historical. |
| R-09 AWS cleanup | **Not executed** | Sandbox retained because teardown would destroy the live evidence; requires the explicit destructive step. |
| R-10 client-id guard | **Fixed** | `MqttSink` rejects a client id mismatch on an AWS IoT host. |
| R-11 test gaps | **Mostly fixed** | 147 tests; redaction, version, status failure, LWT, client-id and requirements tests added. |
| R-12 status counters | **Fixed** | `/stats` now exposes status sent/failed/last_error. |
| R-13 decision record | **Fixed** | `docs/decisions/0003-supportability.md` added. |
| R-14 bundle tail | **Fixed** | Support bundle seeks to the last 1 MB instead of reading the whole log. |

Live component: **1.0.10** deployed and RUNNING; telemetry and `version: 1.0.10`
heartbeat observed in AWS. CI and security are re-run after this commit.
