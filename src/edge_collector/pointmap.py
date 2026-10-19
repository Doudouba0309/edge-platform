"""Versioned point-map contract for declarative protocol sources.

The point map is site configuration, not code. It maps a logical device and
metric to a protocol address and to the engineering value that should become a
:class:`Sample`. Phase 1A validates and normalises the document; the Modbus
source is deliberately separate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from edge_collector.identifiers import DEVICE_ID_PATTERN

POINT_MAP_VERSION = 1
METRIC_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
SOURCE_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
POINT_MAP_SCHEMA_ID = "https://edge-intelligence.example/schemas/point-map.schema.json"


class PointMapError(ValueError):
    """A point map could not be read or validated."""


PointType = Literal[
    "bool",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "float32",
    "float64",
    "string",
]
WordOrder = Literal["big", "little"]


class Point(BaseModel):
    """One metric at one protocol address."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(pattern=METRIC_PATTERN, description="Stable metric name")
    function: Literal["coil", "discrete_input", "holding_register", "input_register"] = Field(
        description="Modbus function family"
    )
    address: int = Field(
        ge=0,
        le=65535,
        description="Zero-based protocol address, not a 40001-style reference",
    )
    type: PointType = Field(description="Wire type")
    scale: float = Field(default=1.0, allow_inf_nan=False)
    offset: float = Field(default=0.0, allow_inf_nan=False)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    deadband: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    word_order: WordOrder = Field(default="big", description="Register order for 32/64-bit values")
    byte_order: WordOrder = Field(default="big", description="Byte order inside each register")
    length: int | None = Field(
        default=None,
        ge=1,
        le=125,
        description="Number of registers for a string; required only for string",
    )
    description: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _validate_function_and_type(self) -> Point:
        register = self.function in ("holding_register", "input_register")
        bit = self.function in ("coil", "discrete_input")
        if bit and self.type != "bool":
            raise ValueError(f"{self.function} requires type 'bool', got {self.type!r}")
        if register and self.type == "bool":
            raise ValueError("register points cannot use type 'bool'; use a coil/bit point")
        if self.type == "string":
            if self.length is None:
                raise ValueError("string points require length (registers)")
        elif self.length is not None:
            raise ValueError("length is only valid for string points")
        if bit and (self.scale != 1.0 or self.offset != 0.0 or self.deadband is not None):
            raise ValueError("coil/discrete points do not support scale, offset or deadband")
        return self


class Slave(BaseModel):
    """One Modbus unit/slave on a source connection."""

    model_config = ConfigDict(extra="forbid")

    unit_id: int = Field(ge=0, le=255, description="Modbus unit/slave id")
    device_id: str = Field(
        pattern=DEVICE_ID_PATTERN,
        description="Logical asset; this becomes Sample.device_id",
    )
    points: list[Point] = Field(min_length=1)


class ModbusTcpSource(BaseModel):
    """One Modbus TCP connection and its slaves."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=SOURCE_ID_PATTERN, description="Stable connection name")
    type: Literal["modbus_tcp"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=502, ge=1, le=65535)
    timeout_s: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    retries: int = Field(default=2, ge=0, le=10)
    poll_interval_s: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    slaves: list[Slave] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_units(self) -> ModbusTcpSource:
        seen: set[int] = set()
        for slave in self.slaves:
            if slave.unit_id in seen:
                raise ValueError(f"duplicate unit_id {slave.unit_id} in source {self.id!r}")
            seen.add(slave.unit_id)
        return self


class PointMap(BaseModel):
    """The complete, versioned point-map document."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = Field(description="Point-map schema version; currently 1")
    source: ModbusTcpSource

    @model_validator(mode="after")
    def _unique_metrics(self) -> PointMap:
        seen: set[tuple[str, str]] = set()
        for slave in self.source.slaves:
            for point in slave.points:
                key = (slave.device_id, point.metric)
                if key in seen:
                    raise ValueError(
                        f"duplicate metric for device {slave.device_id!r}: {point.metric!r}"
                    )
                seen.add(key)
        return self

    @property
    def point_count(self) -> int:
        return sum(len(slave.points) for slave in self.source.slaves)


def load_point_map(path: str | Path) -> PointMap:
    """Read and validate one YAML point map."""
    cfg_path = Path(path)
    try:
        raw = cfg_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PointMapError(f"cannot read point map {cfg_path}: {exc}") from exc
    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PointMapError(f"invalid YAML in {cfg_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PointMapError(f"{cfg_path} must contain a YAML mapping at the top level")
    try:
        return PointMap.model_validate(data)
    except ValidationError as exc:
        raise PointMapError(f"invalid point map ({cfg_path}):\n{exc}") from exc


def point_map_json_schema() -> dict[str, Any]:
    """Generate the committed JSON Schema from the Pydantic models."""
    schema: dict[str, Any] = PointMap.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = POINT_MAP_SCHEMA_ID
    schema["title"] = "Edge Platform point map"
    schema["description"] = (
        "Versioned mapping from a Modbus source/slave/device to named metrics. "
        "Addresses are zero-based protocol offsets, not 40001-style references."
    )
    return schema


def dumps_point_map_schema() -> str:
    return json.dumps(point_map_json_schema(), indent=2, sort_keys=True) + "\n"


def write_point_map_schema(path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else Path("schemas/point-map.schema.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps_point_map_schema(), encoding="utf-8")
    return target


if __name__ == "__main__":
    print(write_point_map_schema())
