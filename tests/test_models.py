"""Contract tests for the canonical models and topic names."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from edge_collector.identifiers import DEVICE_ID_PATTERN, GATEWAY_ID_PATTERN
from edge_collector.models import Batch, Quality, Sample, SourceKind, utcnow
from edge_collector.topics import status_topic, telemetry_topic


def _sample(**overrides: object) -> Sample:
    payload: dict[str, object] = {
        "device_id": "plc-line-1",
        "metric": "temperature",
        "value": 25.221,
        "ts": datetime(2026, 10, 16, 10, 0, tzinfo=UTC),
        "source": SourceKind.OPCUA,
    }
    payload.update(overrides)
    return Sample(**payload)  # type: ignore[arg-type]


def test_naive_sample_timestamp_is_treated_as_utc() -> None:
    sample = _sample(ts=datetime(2026, 10, 16, 10, 0))
    assert sample.ts == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    assert sample.ts.tzinfo is not None


def test_aware_sample_timestamp_is_converted_to_utc() -> None:
    local = datetime(2026, 10, 16, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    sample = _sample(ts=local)
    assert sample.ts == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    assert sample.ts.utcoffset() == timedelta(0)


def test_batch_produced_at_is_normalised_to_utc(make_batch) -> None:
    batch = make_batch(produced_at=datetime(2026, 10, 16, 10, 0))
    assert batch.produced_at == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    assert batch.produced_at.tzinfo is not None


def test_batch_round_trips_through_json(make_batch) -> None:
    original = make_batch(seq=9, samples=3)
    assert Batch.from_json(original.to_json()) == original


def test_batch_json_is_compact(make_batch) -> None:
    raw = make_batch().to_json()
    assert b" " not in raw
    assert b"\n" not in raw


def test_schema_version_is_pinned(make_batch) -> None:
    batch = make_batch()
    with pytest.raises(ValidationError):
        Batch(
            schema_version="2.0",
            gateway_id=batch.gateway_id,
            device_id=batch.device_id,
            seq=0,
            samples=batch.samples,
        )


def test_empty_batch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Batch(gateway_id="gw-factory-7", device_id="plc-line-1", seq=0, samples=[])


def test_negative_sequence_is_rejected(make_batch) -> None:
    with pytest.raises(ValidationError):
        make_batch(seq=-1)


def test_samples_must_share_the_batch_device(make_batch) -> None:
    batch = make_batch(samples=1)
    foreign = _sample(device_id="plc-line-2", ts=utcnow(), source=SourceKind.SIM)
    with pytest.raises(ValidationError):
        Batch(
            gateway_id=batch.gateway_id,
            device_id=batch.device_id,
            seq=0,
            samples=[batch.samples[0], foreign],
        )


@pytest.mark.parametrize("quality", list(Quality))
def test_quality_values_are_preserved(quality: Quality) -> None:
    assert _sample(quality=quality).quality is quality


@pytest.mark.parametrize("bad", ["", "plc/1", "plc+1", "plc#", "plc 1", ".plc"])
def test_sample_rejects_unsafe_device_ids(bad: str) -> None:
    with pytest.raises(ValidationError):
        _sample(device_id=bad)


def test_batch_rejects_unsafe_gateway_id(make_batch) -> None:
    batch = make_batch()
    with pytest.raises(ValidationError):
        Batch(
            gateway_id="gw/1",
            device_id=batch.device_id,
            seq=0,
            samples=batch.samples,
        )


def test_batch_rejects_unsafe_device_id(make_batch) -> None:
    batch = make_batch()
    with pytest.raises(ValidationError):
        Batch(
            gateway_id=batch.gateway_id,
            device_id="plc/1",
            seq=0,
            samples=batch.samples,
        )


def test_identifier_patterns_are_exported() -> None:
    assert GATEWAY_ID_PATTERN.startswith("^")
    assert DEVICE_ID_PATTERN.startswith("^")


def test_telemetry_topic_is_the_frozen_v1_shape() -> None:
    assert telemetry_topic("gw-factory-7", "plc-line-1") == "edge/gw-factory-7/plc-line-1/telemetry"


def test_status_topic_is_gateway_scoped() -> None:
    assert status_topic("gw-factory-7") == "edge/gw-factory-7/status"


@pytest.mark.parametrize("bad", ["", "gw/1", "gw+1", "gw#", "gw 1", "gw\n1", "-gw"])
def test_telemetry_topic_rejects_unsafe_gateway_ids(bad: str) -> None:
    with pytest.raises(ValueError):
        telemetry_topic(bad, "plc-line-1")


@pytest.mark.parametrize("bad", ["", "plc/1", "plc+1", "plc#", "plc 1", ".plc"])
def test_telemetry_topic_rejects_unsafe_device_ids(bad: str) -> None:
    with pytest.raises(ValueError):
        telemetry_topic("gw-factory-7", bad)


@pytest.mark.parametrize("bad", ["", "gw/1", "gw+1", "gw#", "gw 1", "-gw"])
def test_status_topic_rejects_unsafe_gateway_ids(bad: str) -> None:
    with pytest.raises(ValueError):
        status_topic(bad)


def test_topic_allows_thing_name_safe_characters() -> None:
    assert telemetry_topic("GW_1:edge", "line-1.2") == "edge/GW_1:edge/line-1.2/telemetry"
