# Edge Platform — Agent Operating Manual

Operating manual for AI agents working in this repository. Read this before
changing anything. It is the canonical instruction file.

## What this is

This repository is the base image and adapter kit for edge gateways. Those
gateways collect OPC UA, Modbus and MQTT data, normalise it into one `Sample`
shape, batch it, buffer it while the uplink is down, and publish it to AWS IoT
Core through AWS IoT Greengrass V2.

The design is a stack, and the important property is that only the bottom layer
is an image. Everything above it is a Greengrass component or plain
configuration, which is what makes updates cheap.

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Site configuration                                  changes per deployment │
│ point maps · tag names · addresses · thresholds · deadbands                │
│ Adapter component                                   changes per deployment │
│ declarative engine for common protocols · code adapter only when custom    │
╞═══════════ FROZEN DATA CONTRACT · Sample / Batch + JSON Schema ════════════╡
│ Base component set                                          changes rarely │
│ northbound publisher · spool · health · config loader                      │
│ Base image — the only image                                 changes rarely │
│ OS · runtime · nucleus · provisioning · hardening · digest-pinned          │
└────────────────────────────────────────────────────────────────────────────┘
```

Only the bottom layer is an image; everything above it is a Greengrass
component or plain configuration.

**The base owns everything from the data contract northward. The site owns everything south of it.** If a change would make two sites' base images differ, it belongs south of the line.

Northward is the northbound path toward AWS IoT Core: device identity, mutual
TLS, telemetry envelope, batching, store-and-forward, health, deployment
mechanics and logging. Southward is protocol, device quirks, register layout,
byte and word order, scaling, polling cadence, serial framing, vendor dialects
and connectivity. The frozen contract is `Sample` / `Batch` plus its JSON
Schema.

The design documents — proposal, roadmap and decision register — live in
`docs/`.

## Working agreement

Work one explicitly scoped task at a time. Do not proceed to the next task
without an instruction. Report what you did, then stop.

## Platform scope

**Tier 1 is arm64 and x86_64.** Both architectures are built and smoke-tested
on every commit that changes code, images or configuration. Documentation-only
commits may skip the pipeline. A change verified on only one of them is not done.

**Tier 2 is armv7.** It is admitted only with a named deployment and its own CI
job. No speculative armv7 work.

**Explicitly out of scope: armv6, RISC-V, musl.** Do not add support for them.

**The delivery unit is a component plus configuration.** A new image is
justified only by hardware or firmware, never by protocol or site.

**Component namespace.** Greengrass components live under
`io.github.doudouba0309.EdgePlatform`. Client and site names belong in
configuration, thing groups and deployment names, never in component names.
Revisit the prefix before the first real client publish if a company domain is
adopted.

**Execution mode.** Components run in process mode (`NoContainer`); the
collector is a normal Linux process, not a nested container.

## Adapters

**Declarative first.** Prefer a point map over code. A code adapter is the
escape hatch for genuinely custom protocols.

**Never invent a register map.** It comes from a vendor document, a captured
trace, or a human. Refusing is a valid outcome.

**Never ship an adapter without a surrogate to test against and a passing
conformance report.** If you cannot build the surrogate, you cannot ship the
adapter.

## Ground rules

Violating these breaks the build, leaks credentials, or silently corrupts data.

1. **Never commit secrets.** `certs/`, `.env`, `*.pem`, `*.key` are git-ignored.
   A leaked IoT private key means rotating a field device.
2. **Component versions are immutable.** Never edit a published Greengrass
   component version in place — bump `GG_COMPONENT_VERSION`.
3. **The wire format is a contract.** If you change `Sample` or `Batch`,
   regenerate the committed JSON Schema — a test fails if the committed schema
   drifts from the models. The schema and its generator land with the
   toolchain.
4. **Respect the layering.** Sources only normalise into `Sample`; sinks only
   transport a `Batch`; the pipeline owns batching, ordering and retry. A sink
   must never inspect where a sample came from.
5. **`emit` must never block.** It runs on paho's thread and asyncua's task.
   Anything synchronous goes through `asyncio.to_thread`.
6. **Failures must be counted, not swallowed.** Use `SinkUnavailable` to signal
   "buffer it"; increment a counter for anything you drop.
7. **Edge constraints.** No web framework, no heavy runtime dependency, no
   unbounded memory. The bounded queue and the spool budget exist for a device
   with 1 GB of RAM.
8. **Scripts are idempotent and non-interactive.** Support `--yes` for
   destructive operations and `--dry-run` (`DRY_RUN=1`) for AWS mutations.
9. **Public behaviour changes need a test.** A change without a test that fails
   before it and passes after it is not done.

## Invariants and contracts

- **Topics**: `edge/<gateway_id>/<device_id>/telemetry`, `edge/<gateway_id>/status`.
- **Batching**: a batch flushes at `max_samples` OR after `flush_interval_s`,
  whichever comes first. There is no third trigger.
- **Ordering**: once anything is in the spool, new batches queue *behind* it.
  Nothing overtakes the backlog. This is the strongest guarantee in the codebase.
- **Overflow**: `drop_oldest` or `drop_newest`. There is deliberately no `block`
  policy — a synchronous `emit` cannot block safely.
- **Quality**: `good | uncertain | bad | stale`, mapped from OPC UA `StatusCode`.
- **`filtered` is not `dropped`.** `filtered` counts values suppressed on purpose
  (OPC UA deadband). `dropped` counts genuine loss. Never conflate them in output
  or in a metric name - an agent reading `/stats` must be able to tell intentional
  filtering from data loss.
- **Timestamps**: always timezone-aware UTC on the wire; naive input is treated
  as UTC.
- **Health**: `/readyz` is 200 only when every enabled source is connected.
- **Spool budget** applies to payload bytes, not file size (SQLite does not
  return freed pages promptly).
- **The AWS artifacts must agree with the collector.** The IoT policy's
  `iot:Publish` topics, its `iot:Connect` client id, and the recipe's IPC
  access-control resources are all checked against the topics and client id the
  collector actually uses, by a drift test. That test reads the real policy
  heredoc and the real recipe, so editing either one without the collector (or
  vice versa) fails the build instead of failing on a plant floor.

## Traps that already bit us

Do not reintroduce these. Each was a real failure:

1. **asyncua binds the notification handler to the `Subscription`**, not to
   individual monitored items. `subscribe_data_change()` takes no `handler=`.
   Passing one raises at runtime and the source silently reconnect-loops while
   the collector still reports healthy. A contract test must pin this once the
   OPC UA source lands.
2. **SQLite connections are thread-affine.** Access from `asyncio.to_thread`
   worker threads needs `check_same_thread=False` plus an `RLock`.
3. **Never budget the spool on file size.** Page counts do not shrink after
   deletes, so the enforcement loop cannot converge and purges the whole buffer.
4. **`getattr(dict, "key", default)` always returns the default.** The Prometheus
   renderer had this bug; handle dicts and objects explicitly.
5. **An editable install must happen after `src/` exists.** Otherwise uv writes
   console-script entry points for a package with no modules.
6. **`head` is a real command.** Do not name a bash function `head`.
7. **The two platforms use different wildcards, and `*` is the one that spans `/`.**
   In an **IoT Core policy**, topic resources use IAM globs: `*` (any characters,
   including `/`) and `?` (one). MQTT `+` and `#` are *literal* characters there,
   so rewriting `topic/edge/thing/*/telemetry` to `+` would break it. In a
   **Greengrass IPC** access-control resource, `+`/`#` *and* `*` all work, and `*`
   again spans separators, so `edge/*/telemetry` already covers
   `edge/<gateway>/<device>/telemetry`. Both were almost "fixed" into a broken
   state by reasoning from MQTT semantics; an AWS-artifact drift test must pin
   the documented behaviour once the AWS path lands.
8. **A recipe manifest with no `Platform` key applies to all platforms**, and a
   core device must match at least one manifest or the deployment simply fails.
   Listing only `aarch64` silently excludes every x86_64 device, and a pure-Python
   artifact does not exempt you — the rule is unconditional.

## Never run these without explicit human instruction

These are destructive or irreversible:

| Command | Why |
|---|---|
| Any `git push`, force-push, or history rewrite | Not yours to decide |
| AWS provisioning, component-publish or deploy scripts | Mutate a real AWS account. Use `--dry-run` first |
| AWS teardown without `--yes` | Deletes AWS resources and certificates |

Nothing else in this repository is destructive.

## Build and verification

The gates, all runnable:

- `make check` — ruff format/check, `mypy --strict`, unit tests.
- `make verify` — `check` plus `scripts/smoke-local.sh`, the local mTLS and
  store-and-forward outage/replay check.
- `make smoke` — `scripts/smoke-image.sh`, which builds and boots both Tier 1
  images.
- `make sbom` — `scripts/sbom.sh`, which generates CycloneDX JSON for the
  collector images.
- `make sbom-nucleus` — the same scan for the nucleus images.
- `make nucleus-smoke` — builds and verifies the offline Greengrass nucleus on
  both architectures.

`make check` needs no Docker. The smoke targets and both SBOM targets need
Docker; `make verify` also needs the host Mosquitto clients. Do not invent
commands that do not run, and do not claim a change is verified by a command
that has not been defined.

## Definition of done

A change is complete when all of these hold:

- [ ] `make check` passes
- [ ] `make verify` passes for transport or spool changes
- [ ] `make smoke` passes for image changes
- [ ] `make sbom` succeeds for collector image changes
- [ ] `make sbom-nucleus` succeeds for nucleus changes
- [ ] `make nucleus-smoke` passes for nucleus changes
- [ ] new behaviour has a test that fails without the change
- [ ] `docs/` updated if behaviour, config or operations changed
- [ ] the committed JSON Schema regenerated if the wire format moved
- [ ] no secret, certificate or `.env` file staged for commit

## Notes on the AWS path

The collector has not been provisioned, published or deployed into a real AWS
account yet. The sandbox itself has been verified with read-only CLI calls and an
empty private bucket. Treat every runtime AWS-facing claim as a design intention.

These parts are verifiable offline:

- **Mutual TLS.** `scripts/smoke-local.sh` runs the MQTT sink against a local
  broker that requires a client certificate, proving certificate resolution,
  hostname verification, client-cert authentication and the publish topic. The
  AWS IoT Core endpoint, policy and authorisation remain unexercised.
- **Greengrass IPC sink.** `GreengrassIpcSink` is implemented and unit-tested
  against a fake IPC client. A real publish requires a provisioned core and a
  deployed collector component.
- **Containerised nucleus.** `scripts/smoke-nucleus.sh` builds the pinned
  nucleus `2.18.4` image and verifies "Launched Nucleus successfully", the IPC
  socket, identity reuse across a restart, and clean SIGTERM, all offline. The
  boundary it proves: the nucleus only authenticates IPC clients it launched
  itself, so an outside client is refused with `KeyError: 'SVCUID'` and must
  degrade to spooling rather than crashing. Re-run this after touching the
  Greengrass sink.

When you do run the AWS path: `--dry-run` first, check IAM permissions, then
tear down to clean up. An offline Greengrass nucleus cannot install
`aws.greengrass.Cli`, so `greengrass-cli` only appears after one successful
cloud provisioning run.

## Handover note

This repository is being built task by task from the documents in `docs/`. The
development environment at `../dev-env-setup` is a read-only reference and is
not part of this repository. Do not copy from it blindly, and do not treat its
commands, paths or tooling as belonging here. The dev-environment sections —
CLI, MCP server, compose stack, simulators — return when the toolchain lands.
