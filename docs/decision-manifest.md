# Phase 1+ Decision Manifest

- **Snapshot:** 18 October 2026
- **Current live state:** component `1.0.10` is RUNNING on the AWS sandbox; telemetry and status heartbeat are observed; 149 tests pass.
- **Phase 1 target:** Solar + Modbus TCP, starting with a local surrogate. See [Solar + Modbus TCP Scope](solar-modbus-scope.md).
- **Purpose:** list the decisions needed from the point-map contract onward, with a recommended default for each.

## How to use this

- **Must decide now:** needed before the point-map schema is frozen.
- **Before implementation:** can wait until the preceding task is nearly done.
- **Before v1:** needed before shipping to a client.
- **Client input:** needs the client, their IT/security team, or the test site.

If you agree with every recommendation, reply **“approve defaults.”**
If not, reply with the decision IDs, for example: **“D1 JSON, D4 add uint32, D21 CloudWatch.”**

## 1. Point-map contract (#2)

| ID | Decision | Options | Recommendation | Why / impact | Needed |
|---|---|---|---|---|---|
| D1 | File format | YAML / JSON / TOML | **YAML** | Human-reviewable by a controls engineer; diffs cleanly. | Must decide now |
| D2 | Scope | One file per source / one file per gateway / one file per site | **One file per source** | Avoids a giant site file; each device/source can be versioned independently. | Must decide now |
| D3 | Schema versioning | No version / `version: 1` / date version | **`version: 1`** | Allows a future incompatible point-map change to fail loudly. | Must decide now |
| D4 | Supported data types | Minimal / broad subset | **`bool`, `int16`, `uint16`, `int32`, `uint32`, `float32`, `float64`, `string`** | Covers common PLCs without pretending to support every vendor type. Add more on evidence. | Must decide now |
| D5 | Byte and word order | Global default only / per-point override | **Big-endian default, per-point override** | Many devices differ on 32-bit word order; override is essential. | Must decide now |
| D6 | Unknown fields | Ignore / warn / reject | **Reject** | A typo in a point map should fail before deployment, not silently read the wrong register. | Must decide now |
| D7 | Duplicate metrics | Allow / reject / rename | **Reject within a source** | Duplicate names make downstream data ambiguous. | Must decide now |
| D8 | Metric naming | Free text / restricted identifier | **`[a-z][a-z0-9_]*`, max 64 chars** | Keeps topics, dashboards and alerts predictable. | Must decide now |
| D9 | Scaling | `scale` + `offset` / raw only | **`value * scale + offset`**, optional | Standard and easy to review; raw-only is useless for engineering units. | Must decide now |
| D10 | Deadband | No deadband / per-point absolute deadband | **Optional per-point absolute deadband** | Reduces cost and noise; must be per point because sensors differ. | Must decide now |
| D11 | Configuration location | Baked into recipe / local file / S3 + component config | **Point map in S3, referenced by component configuration** | Enables remote update without a new image; the component stays generic. | Before implementation |
| D12 | Map validation | Syntax only / semantic too | **Both; no hardware check in v1** | Catch duplicate metrics, impossible addresses and type conflicts before deployment. | Must decide now |
| D13 | Units | Free text / UCUM / fixed list | **Free text in v1, UCUM later** | Avoids blocking on a unit standard; normalise when a real site needs it. | Before v1 |

## 2. Modbus TCP (#3)

| ID | Decision | Options | Recommendation | Why / impact | Needed |
|---|---|---|---|---|---|
| D14 | Library | `pymodbus` / custom implementation | **`pymodbus`, pinned** | A well-tested protocol implementation is safer than a hand-rolled client. | Before implementation |
| D15 | Read functions | All / subset | **Coils (1), discrete inputs (2), holding registers (3), input registers (4)** | Covers the common factory cases. | Before implementation |
| D16 | Read strategy | One request per point / block reads | **Block reads with per-point mapping** | Far fewer requests, lower latency and less device load. | Before implementation |
| D17 | Writes | Read-only / allow writes | **Read-only in v1** | Telemetry collection is the product; writes are a separate safety-critical feature. | Must decide now |
| D18 | Polling cadence | Global / per source / per point | **Per-source interval with optional per-point override** | Different devices and registers need different rates. | Before implementation |
| D19 | Failure behaviour | Stop source / mark bad and retry | **Mark samples bad, count errors, reconnect with backoff** | A single bad register must not take down the gateway. | Before implementation |
| D20 | TCP test bench | Real PLC / local surrogate | **Local surrogate with fault injection first** | Deterministic, safe, repeatable; real PLC later for HIL. | Before implementation |

## 3. Modbus RTU (#4)

| ID | Decision | Options | Recommendation | Why / impact | Needed |
|---|---|---|---|---|---|
| D21 | RTU transport | `pymodbus` RTU + `pyserial` / custom serial | **`pymodbus` RTU with `pyserial`** | Same protocol library as TCP; serial handling is well tested. | Before implementation |
| D22 | Serial defaults | Fixed / configurable | **Configurable baud, parity, stop bits, timeout; default 9600 8N1** | Real devices vary; one fixed setting will fail somewhere. | Before implementation |
| D23 | RTU surrogate | TCP only / pseudo-terminal / USB-RS485 | **Pseudo-terminal surrogate first, then USB-RS485 HIL** | PTY tests framing/CRC/timing; HIL tests the real electrical layer. | Before implementation |
| D24 | HIL requirement | Optional / mandatory before ship | **Mandatory before shipping RTU** | Serial/electrical problems are invisible in a PTY. | Before v1 |
| D25 | HIL hardware | Buy / borrow / client site | **Decide a small budget or use the client’s test site** | Needs a gateway, USB-RS485 adapter and a sensor/PLC or second adapter. | Client input |

## 4. Supportability and remote access (#5)

| ID | Decision | Options | Recommendation | Why / impact | Needed |
|---|---|---|---|---|---|
| D26 | Log shipping | None / CloudWatch / customer SIEM | **CloudWatch first, customer SIEM later** | Fastest path to remote evidence; SIEM is a site-specific integration. | Before v1 |
| D27 | Remote access | Embedded SSH / AWS IoT Secure Tunneling / SSM / WireGuard | **A — evidence only for v1; no tunnel yet** | No open inbound port; logs, alarm and support bundle are the support path. | Decided |
| D28 | Shell policy | Full shell / restricted / none | **No shell by default; optional audited session over tunnel** | The default support path is logs + support bundle + deployment. | Before v1 |
| D29 | Support bundle upload | Email/ticket / S3 presigned / client portal | **S3 presigned upload with expiry** | Keeps large logs out of chat and avoids long-lived credentials. | Before v1 |
| D30 | Log retention | 7 / 14 / 30 / 90 days | **30 days in CloudWatch, 7 days local** | Balances evidence, cost and device disk. Needs client confirmation. | Client input |
| D31 | Data sensitivity | No customer data / redacted / full | **Redacted configs; never credentials or private keys** | Support evidence must be safe to move across borders. | Must decide now |
| D32 | Client remote access approval | Not needed / written approval / site tooling | **Written approval and a named support identity per site** | Client IT/security will require this for another country. | Client input |

## 5. AWS operations (#6)

| ID | Decision | Options | Recommendation | Why / impact | Needed |
|---|---|---|---|---|---|
| D33 | Sandbox lifecycle | Keep live / tear down / keep until v1 | **Keep for Phase 1** | Preserves the live proof and support path; teardown later. | Decided |
| D34 | Provisioning | Manual CLI / repeatable scripts | **Repeatable scripts with `--dry-run` and `--yes`** | The manual path took many corrections and is not safe to repeat from memory. | Before next AWS test |
| D35 | Naming | Free / fixed convention | **`edge-platform-<env>-<thing>`; tag `project=edge-platform`, `environment=sandbox`** | Makes cleanup and cost tracking reliable. | Before next AWS test |
| D36 | AWS architecture proof | arm64 only / both | **arm64 live proof; x86_64 image CI; add x86 core only if a client needs it** | Avoids paying for a second core without a requirement. | Before v1 |

## 6. V1 scope (#7)

| ID | Decision | Options | Recommendation | Why / impact | Needed |
|---|---|---|---|---|---|
| D37 | Protocols in v1 | Modbus TCP / + RTU / + OPC UA | **Solar + Modbus TCP first, RTU second, OPC UA after** | Each protocol needs a surrogate and HIL; one at a time is honest. | Decided |
| D38 | Client test participation | None / remote / on-site | **Remote staging first; on-site/HIL for the final gate** | The client is in another country; design the evidence loop before shipping. | Client input |
| D39 | Acceptance tests | Unit only / bench + 24h soak | **Bench, 24h soak, network loss, power loss, disk-full, restart** | A gateway that works for five minutes is not v1. | Before v1 |
| D40 | Production security review | Skip / internal / client-led | **Client-led review before any production certificate** | Remote access and data residency need approval. | Before v1 |
| D41 | First pilot site | One site / multiple | **One site, one protocol family, one gateway** | Limits blast radius and makes support evidence readable. | Client input |

## Recommended default bundle

If you want to move quickly, approve this set:

- **YAML**, one file per source, `version: 1`, strict unknown-field rejection.
- Types: bool, int16, uint16, int32, uint32, float32, float64, string.
- Big-endian default, per-point word/byte order override.
- Scale + offset, optional deadband, metric regex `[a-z][a-z0-9_]*`.
- Point map in S3, referenced by component configuration; validate syntax and semantics before deployment.
- Modbus: `pymodbus`, functions 1–4, block reads, read-only v1, per-source polling, bad-quality on failure.
- RTU: `pymodbus` RTU + `pyserial`, configurable serial, PTY surrogate then mandatory USB-RS485 HIL.
- Support: CloudWatch 30 days, local 7 days, support bundle to S3 presigned, no inbound SSH, AWS IoT Secure Tunneling only, audited.
- AWS: tear down the current sandbox after proof, then script provisioning with tags.
- V1: Solar + Modbus TCP first, then RTU, one pilot site, arm64 live proof, 24h soak and failure tests before shipping.

## What I will not do without a decision

- Invent a register map or point mapping.
- Enable remote shell access by default.
- Ship an adapter without a surrogate and HIL.
- Change the frozen `Sample`/`Batch` schema.
- Deploy to production or expose inbound SSH.

## What can proceed while you decide

The next coding task is the **point-map schema and validator**. The decisions above determine its fields, but the skeleton can be drafted with the recommended defaults and adjusted once you choose.

