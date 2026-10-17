# Open questions — decision register for the new platform project

Companion to [edge-platform-proposal.html](edge-platform-proposal.html) and
[edge-platform-roadmap.html](edge-platform-roadmap.html).

**How to answer:** quote the ID and the option, e.g. `1A, 2 yes, 3 accept, rest = defaults`.
Anything marked *default* I will otherwise assume and state back to you.

**Where to spend your attention.** Four of these are **one-way doors** — expensive or impossible to
change after the first real deployment. Everything else is cheap to reverse.

| One-way door | Why |
|---|---|
| Q6 component namespace | Greengrass component names are account-scoped and **immutable per published version**; consumers resolve them by name |
| Q7 topic scheme | IoT rules, policies and downstream consumers hard-code topic filters |
| Q8 payload contract | Already published as JSON Schema; consumers validate against it |
| Q13 process vs container mode | Changing it later changes how components are packaged and deployed |

---

## Group 1 — Blocking: needed before I write the first file

### Q1. Where does the project live, and how do I get write access?

The DSH sandbox is scoped to `…/edge-dev/dev-env-setup`, and writes to the parent are **denied**
(confirmed by probe). Options:

- **A (recommended)** — you create `…/edge-dev/edge-platform` and start a DSH session rooted there.
  Clean sandbox, clean history. This session's context does not follow, but all artifacts are on disk
  and readable from the new session.
- **B** — build at `dev-env-setup/platform/` inside the current workspace. Zero friction, starts
  immediately, mixes the two projects; git makes relocating trivial.
- **C** — keep this session and grant `danger-full-access` per operation. Works, but dozens of
  approval prompts.

**Also:** confirm the exact path you want.

### Q2. Repo scope — platform only, or self-contained?

- **Self-contained (recommended)** — the platform plus its own local dev loop (compose stack,
  simulators), CI and docs. A team can clone it and run it.
- **Platform only** — the dev loop stays in `dev-env-setup`, which points at the platform. Cleaner
  separation, but onboarding needs two repos.

### Q3. Version control?

Neither `dev-env-setup` nor its parents are git repositories today — 227 tests and all the design
work have no history. Confirm:

- initialise the new repo with an initial commit (**recommended**);
- and whether to also `git init` `dev-env-setup` to preserve its history (**recommended**, it is one
  command and phases 1–4 will keep referencing it).

---

## Group 2 — Needed during Phase 0 (defaults will be assumed)

### Q4. CI platform
**Default: GitHub Actions**, with all pipeline logic in `make` targets so the provider is swappable.
Alternatives: GitLab CI, Jenkins, or provider-neutral `make` only for now.

### Q5. Image registry
**Default: none yet** — build locally and keep images as CI artifacts. Wire GHCR or ECR when we first
ship. Tell me if a registry already exists.

### Q6. Greengrass component namespace *(one-way door)*
Currently the placeholder `com.example.EdgeCollector`. I need your real reverse-DNS prefix before the
first publish, e.g. `com.acme.EdgeGateway`. Can use the placeholder until then.

### Q7. Thing and topic naming *(one-way door)*
**Default: keep the current scheme** — thing name = gateway id, core thing = `<gateway>-core`,
telemetry on `edge/<gateway>/<device>/telemetry`, status on `edge/<gateway>/status`.
Do you have a fleet convention (site codes, asset tags, serials) this should follow instead?

### Q8. Python package name *(one-way door)*
**Default: keep `edge_collector`** to avoid churn across the existing tests. Alternative:
`edge_gateway`, which describes the base more accurately.

### Q9. First two protocols
**Default: OPC UA + Modbus TCP.** Adding protocols later is additive, so this is not a one-way door.
Flag anything that is a **must-have in the first three** (BACnet, a vendor serial protocol, CAN) —
that changes Phase 1/2 ordering.

### Q10. Base OS
**Default: Ubuntu 24.04** — it matches the VM already verified here, so the container and the target
share a userland. Alternative: Debian slim (smaller), or `amazonlinux:2023` for fidelity to AWS's
reference container documentation.

### Q11. Device resource ceiling
**Default: design to a 1 GB RAM device**, image around 400 MB. Is there a hard ceiling I should
design to (smaller device, stricter flash budget)?

### Q12. Smoke-test memory assertion
I need a concrete number to fail the build on. **Default: collector RSS below 150 MB** steady state
after a batch cycle. Tell me if that is too strict or too generous.

### Q13. Component execution mode *(one-way door)*
**Default: process mode (`NoContainer`)** — required anyway for Greengrass running inside a
container, simpler, and no overlay/kernel prerequisites. Confirm.

### Q14. How point maps reach the device
**Default: Greengrass component configuration**, merged per thing or group, with a local config file
as a fallback for non-Greengrass runs. This shapes the engine's config loader.

---

## Group 3 — Needed by Phase 2–3

### Q15. Surrogate source, per first protocol
A lab device, a customer capture, or simulators built from vendor documents?
**Default: simulators built from the documents now**, augmented by a real capture when one is
available. Phase 2 depends on this more than on any code.

### Q16. Write policy
**Default: read-only for v1.** Is a write path (setpoints, commands) required early? It changes the
safety and review model.

### Q17. Review owner
Who signs off an adapter change and its conformance report — a controls engineer, a platform
engineer, or both?

### Q18. Air-gapped sites
Do any deployments install with **no internet access**? If yes, every artifact needs a bundled
per-architecture wheelhouse, which changes the build. **Default: assume not for v1**, keep the option
in the recipe.

### Q19. Data destination beyond IoT Core
Is IoT Core the endpoint, or does data route onward (SiteWise, Timestream, S3, your own consumer)?
This affects whether the topic scheme needs per-asset granularity for IoT rules.

### Q20. Fleet size in year one
Roughly how many sites? It informs rollout rate limits, whether per-device or fleet provisioning is
needed, and how much CI/registry investment is justified.

### Q21. Existing estate to integrate with — **asked last round, never answered**
Is there already a device-management system, an existing Greengrass deployment, an existing MQTT
broker, or a historian this must fit into rather than replace? This is the largest unknown in the
whole plan: if something exists, the base must accommodate it instead of assuming a greenfield site.

### Q22. First real site's hardware
What box, what OS, what NICs or modem? Needed to validate the base image against an actual device,
and to know whether a kernel module or a firmware blob is required.

---

## Group 4 — Facts needed when we first touch AWS

Not needed for Phase 0: the base image, the two-architecture build, the local mutual-TLS smoke test
and the base components are all offline. These become necessary at the first component publish or
device provisioning.

| Fact | Note |
|---|---|
| **AWS region** | Scripts currently default to `ap-southeast-1` |
| **Access method** | A named profile, or `aws sso login` |
| **Which account** | Sandbox or production — I will not mutate a production account without an explicit instruction |
| **Existing IoT things / groups / Greengrass cores** | To avoid colliding with a live fleet |

---

## If you answer only three things

1. **Q1** — file access option, and the path.
2. **Q2** — repo scope.
3. **Q3** — confirm git initialisation.

Everything else has a stated default. I will start the Phase 0 slice, and I will tell you plainly
which parts are proven and which remain designed-but-unverified — the AWS column in particular.
