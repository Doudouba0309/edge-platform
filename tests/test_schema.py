"""Wire-format contract tests.

The JSON Schema in ``schemas/`` is a published interface: IoT rules, Lambda
consumers and agents validate against it. These tests make drift impossible — if
the pydantic models change without regenerating the schema, the build fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from edge_collector.identifiers import DEVICE_ID_PATTERN, GATEWAY_ID_PATTERN
from edge_collector.models import SCHEMA_VERSION, Batch
from edge_collector.schema import (
    batch_json_schema,
    dumps_schema,
    load_schema,
    repo_schema_path,
)

SCHEMA_PATH: Path = repo_schema_path()


def test_committed_schema_matches_the_models() -> None:
    assert SCHEMA_PATH.exists(), f"{SCHEMA_PATH} is missing - run `python -m edge_collector.schema`"
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == batch_json_schema(), (
        "schemas/telemetry-batch.schema.json is out of date. Run `python -m edge_collector.schema`."
    )


def test_schema_file_is_what_the_generator_emits() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == dumps_schema()


def test_schema_declares_the_draft_and_identity() -> None:
    schema = load_schema(SCHEMA_PATH)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].startswith("https://")
    assert schema["title"] == "Edge telemetry batch"


def test_schema_pins_the_schema_version() -> None:
    schema = load_schema(SCHEMA_PATH)
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION


def test_schema_pins_the_identifier_grammar() -> None:
    schema = load_schema(SCHEMA_PATH)
    assert schema["properties"]["gateway_id"]["pattern"] == GATEWAY_ID_PATTERN
    assert schema["properties"]["device_id"]["pattern"] == DEVICE_ID_PATTERN
    assert schema["$defs"]["Sample"]["properties"]["device_id"]["pattern"] == DEVICE_ID_PATTERN


def test_schema_requires_the_envelope_fields() -> None:
    schema = load_schema(SCHEMA_PATH)
    assert set(schema["required"]) == {
        "gateway_id",
        "device_id",
        "seq",
        "samples",
    }


def test_a_real_batch_validates(make_batch) -> None:
    schema = load_schema(SCHEMA_PATH)
    payload = json.loads(make_batch(seq=3, samples=2).to_json())
    Draft202012Validator(schema).validate(payload)


def test_schema_rejects_an_empty_batch(make_batch) -> None:
    schema = load_schema(SCHEMA_PATH)
    payload = json.loads(make_batch().to_json())
    payload["samples"] = []
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_schema_rejects_a_negative_sequence(make_batch) -> None:
    schema = load_schema(SCHEMA_PATH)
    payload = json.loads(make_batch().to_json())
    payload["seq"] = -1
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_schema_rejects_an_unknown_source(make_batch) -> None:
    schema = load_schema(SCHEMA_PATH)
    payload = json.loads(make_batch().to_json())
    payload["samples"][0]["source"] = "carrier-pigeon"
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_schema_rejects_an_unsafe_gateway_id(make_batch) -> None:
    schema = load_schema(SCHEMA_PATH)
    payload = json.loads(make_batch().to_json())
    payload["gateway_id"] = "gw/1"
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_schema_rejects_an_unsafe_device_id(make_batch) -> None:
    schema = load_schema(SCHEMA_PATH)
    payload = json.loads(make_batch().to_json())
    payload["device_id"] = "plc/1"
    assert list(Draft202012Validator(schema).iter_errors(payload))


def test_batches_round_trip_through_the_declared_shape(make_batch) -> None:
    """Anything the schema accepts, Batch must parse — and vice versa."""
    schema = load_schema(SCHEMA_PATH)
    validator = Draft202012Validator(schema)
    original = make_batch(seq=9, samples=3)
    payload = json.loads(original.to_json())
    validator.validate(payload)
    assert Batch.from_json(json.dumps(payload)) == original


@pytest.mark.parametrize("bad_value", [{"nested": True}, [1, 2, 3], None])
def test_schema_rejects_non_scalar_sample_values(make_batch, bad_value: Any) -> None:
    schema = load_schema(SCHEMA_PATH)
    payload = json.loads(make_batch().to_json())
    payload["samples"][0]["value"] = bad_value
    assert list(Draft202012Validator(schema).iter_errors(payload))
