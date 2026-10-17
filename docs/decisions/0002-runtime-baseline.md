# Decision 0002 — Tier 1 runtime baseline

- **Date:** 2026-10-17
- **Status:** accepted

## Decision

The Tier 1 base image is **Ubuntu 24.04**. The Python runtime is **3.12** and
`pyproject.toml` declares `requires-python = ">=3.12"`.

The Greengrass nucleus image remains separate and uses OpenJDK 17.

## Rationale

- The image and the collector run on the same Ubuntu userland.
- The code uses `StrEnum` and `datetime.UTC`, both of which require Python 3.11
  or newer.
- CI and the base image both use Python 3.12, so there is one runtime to test.

## Consequences

- Ubuntu 22.04 with its Python 3.10 is **out of scope** for Tier 1.
- Supporting 22.04 later would require a different image, a newer Python, and a
  deliberate code review; it is not a silent configuration change.
- Revisit this decision before the first real client deployment if 22.04
  becomes a hard requirement.
