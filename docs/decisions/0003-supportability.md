# Decision 0003 — Supportability and remote access

- **Date:** 2026-10-18
- **Status:** accepted for the supportability layer; remote access remains opt-in and needs a site-specific decision.

## Decision

The collector is **offline-first** and produces evidence without opening an
inbound port.

- Container and Greengrass logs are JSON, bounded by rotation, and redacted.
- Gateway presence and heartbeat are published separately from telemetry on
  `edge/<gateway>/status`, through a single status owner.
- A redacted support bundle can be generated on the gateway.
- There is **no inbound SSH** by default.
- Interactive access, if approved for a site, must be outbound-only,
  time-limited, audited, and restricted to a named support identity.
- Component version and package version are separate fields in logs, status and
  the support manifest.
- Heartbeats carry an expiry (`expires_at`) so a consumer can treat silence as
  stale; cloud-side alerting is still required.

## Consequences

- Logs and bundles can leave the site safely after redaction review.
- Missing heartbeats must be alarmed in the cloud; the component cannot report
  its own death.
- CloudWatch shipping, support-bundle upload and an approved tunnel are v1
  operational work, not collector code.
- A future remote shell must never be enabled by default and must pass the
  client’s security review.
