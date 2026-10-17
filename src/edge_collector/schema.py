"""JSON Schema export for the telemetry wire format.

The schema is a published interface: CI and downstream consumers validate
against it, and ``tests/test_schema.py`` fails if the committed file drifts from
the pydantic models. Regenerate with::

    python -m edge_collector.schema
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from edge_collector.models import SCHEMA_VERSION, Batch

SCHEMA_ID = "https://edge-intelligence.example/schemas/telemetry-batch.schema.json"
DEFAULT_SCHEMA_PATH = Path("schemas/telemetry-batch.schema.json")


def repo_schema_path() -> Path:
    """The committed schema inside the repository, independent of the cwd."""
    return Path(__file__).resolve().parents[2] / DEFAULT_SCHEMA_PATH


def batch_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for :class:`Batch`, ready to serialise."""
    schema: dict[str, Any] = Batch.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = SCHEMA_ID
    schema["title"] = "Edge telemetry batch"
    schema["description"] = (
        "One northbound message published by edge-platform to "
        "edge/<gateway_id>/<device_id>/telemetry. "
        "Every sample shares the batch device_id. "
        f"schema_version {SCHEMA_VERSION}."
    )
    # Consumers filter on this, so make it a constant rather than a bare string.
    schema.setdefault("properties", {})["schema_version"] = {
        "const": SCHEMA_VERSION,
        "default": SCHEMA_VERSION,
        "title": "Schema Version",
        "type": "string",
    }
    return schema


def dumps_schema() -> str:
    """Serialise deterministically: sorted keys, two-space indent, trailing newline."""
    return json.dumps(batch_json_schema(), indent=2, sort_keys=True) + "\n"


def write_schema(path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else repo_schema_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps_schema(), encoding="utf-8")
    return target


def load_schema(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else repo_schema_path()
    return cast("dict[str, Any]", json.loads(target.read_text(encoding="utf-8")))


if __name__ == "__main__":
    print(write_schema())
