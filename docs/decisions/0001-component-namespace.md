# Decision 0001 — component namespace and Phase 0 defaults

- **Date:** 2026-10-17
- **Status:** accepted

## Q6 — Greengrass component namespace

Use the component family:

```
io.github.doudouba0309.EdgePlatform
```

Client and site names never appear in component names; they belong in
configuration, thing groups and deployment names. Revisit this prefix before the
first real client publish if a company domain is adopted.

## Q13 — component execution mode

Components run in process mode (`NoContainer`). No Docker or overlay
prerequisites on the gateway; the Python collector runs directly.

## Nucleus

Pin Greengrass nucleus **2.18.4** from the versioned AWS artifact
(`greengrass-2.18.4.zip`, SHA-256
`9d7b620633d09180f81a6b7d31e9dd6bb53dab3c038f32d788ade6469e583d6e`) with
OpenJDK 17. The offline verification image uses a self-signed identity and
`--init`; production installation/provisioning is a later step.

## SBOM

Generate CycloneDX JSON with Syft for the collector and nucleus Tier 1 images.
Publish the files as CI artifacts. There is deliberately no vulnerability-fail
gate yet; that is a later policy decision.
