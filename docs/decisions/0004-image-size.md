# Decision 0004 — Test-core image size

- **Date:** 2026-10-18
- **Status:** accepted for the sandbox; production base still targeted at ~400 MB.

## Decision

The arm64 test-core nucleus image is **601 MB**. It is accepted for the sandbox
because it contains the nucleus, Java, Python 3.12 and the tools needed to run
the collector end to end.

The production base must not inherit this size by accident. It targets ~400 MB
and will be composed separately, with only:
- OS/runtime and nucleus;
- Python runtime needed by the collector;
- no build tools, package caches or test-only utilities.

## Consequences

- The test core is not a production image.
- A future image-slimming task will choose the production base; if it cannot
  reach ~400 MB, the target will be revised deliberately and recorded.
- The current 601 MB image is honest evidence for the tested core, not a
  shipping claim.
