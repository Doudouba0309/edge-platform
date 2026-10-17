"""Canonical telemetry data model.

Everything that flows through the platform — whether it arrived over OPC UA,
Modbus or MQTT — is normalised into a :class:`Sample`, then shipped upstream in
a :class:`Batch`. Keeping one canonical shape here is what makes the transports
interchangeable: the northbound path never needs to know where a value came
from.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edge_collector.identifiers import DEVICE_ID_PATTERN, GATEWAY_ID_PATTERN

SCHEMA_VERSION = "1.0"

#: JSON scalar types a protocol value may collapse to.
ScalarValue = float | int | str | bool


class Quality(str, Enum):
    """OPC UA style quality, kept so downstream can filter bad data."""

    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"
    STALE = "stale"


class SourceKind(str, Enum):
    """Protocol family a sample was normalised from."""

    OPCUA = "opcua"
    MQTT = "mqtt"
    MODBUS = "modbus"
    SIM = "sim"


def utcnow() -> datetime:
    """Timezone-aware UTC now; never a naive local timestamp."""
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Treat naive input as UTC and convert aware input to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Sample(BaseModel):
    """A single measurement from a single metric."""

    model_config = ConfigDict(frozen=True)

    device_id: str = Field(
        pattern=DEVICE_ID_PATTERN,
        description="Logical asset the metric belongs to",
    )
    metric: str = Field(description="Metric name, e.g. 'temperature'")
    value: ScalarValue
    ts: datetime = Field(description="Observation time, always timezone-aware UTC")
    source: SourceKind
    origin: str = Field(
        default="",
        description="Where it came from: OPC UA node id, MQTT topic, or register",
    )
    unit: str | None = None
    quality: Quality = Quality.GOOD
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("ts")
    @classmethod
    def _normalise_ts(cls, value: datetime) -> datetime:
        return _as_utc(value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "metric": self.metric,
            "value": self.value,
            "ts": self.ts.isoformat(),
            "source": self.source.value,
            "origin": self.origin,
            "unit": self.unit,
            "quality": self.quality.value,
            "tags": self.tags,
        }


class Batch(BaseModel):
    """An ordered group of samples published as one northbound message.

    A batch is per device: ``device_id`` names the topic level and every sample
    in it must carry the same device id. Batching is the single biggest lever
    on AWS IoT Core cost, because IoT Core bills per message rather than per
    sample.
    """

    schema_version: str = SCHEMA_VERSION
    gateway_id: str = Field(
        pattern=GATEWAY_ID_PATTERN,
        description="Gateway identity; also the AWS IoT thing name",
    )
    device_id: str = Field(
        pattern=DEVICE_ID_PATTERN,
        description="Logical asset the batch belongs to",
    )
    seq: int = Field(ge=0, description="Monotonic per-process batch counter")
    produced_at: datetime = Field(default_factory=utcnow)
    samples: list[Sample] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _pin_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
        return value

    @field_validator("produced_at")
    @classmethod
    def _normalise_produced_at(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @model_validator(mode="after")
    def _samples_share_device(self) -> Batch:
        mismatch = next(
            (sample for sample in self.samples if sample.device_id != self.device_id),
            None,
        )
        if mismatch is not None:
            raise ValueError(
                "every sample must belong to the batch device_id "
                f"{self.device_id!r}, got {mismatch.device_id!r}"
            )
        return self

    def to_json(self) -> bytes:
        """Compact UTF-8 JSON — no spaces, to keep messages in the 5 KB tier."""
        payload = {
            "schema_version": self.schema_version,
            "gateway_id": self.gateway_id,
            "device_id": self.device_id,
            "seq": self.seq,
            "produced_at": self.produced_at.isoformat(),
            "samples": [sample.as_dict() for sample in self.samples],
        }
        return json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes | str) -> Batch:
        return cls.model_validate_json(raw)
