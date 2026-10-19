"""Modbus TCP source: block reads, decoding, quality and configuration."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from edge_collector.config import load_config
from edge_collector.models import Quality, Sample, SourceKind
from edge_collector.pointmap import PointMap
from edge_collector.sources.modbus_tcp import ModbusTcpSource


class FakeResponse:
    def __init__(
        self,
        *,
        registers: list[int] | None = None,
        bits: list[bool] | None = None,
        error: bool = False,
    ) -> None:
        self.registers = registers or []
        self.bits = bits or []
        self._error = error

    def isError(self) -> bool:  # noqa: N802
        return self._error


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int, int]] = []
        self.raise_on_read = False
        self.registers = [0] * 200
        self.bits = [False] * 200
        self.connected = False

    async def connect(self) -> bool:
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False

    def _response(self, function: str, address: int, count: int) -> FakeResponse:
        self.calls.append((function, address, count, 0))
        if self.raise_on_read:
            raise TimeoutError("simulated timeout")
        if function in ("coil", "discrete_input"):
            return FakeResponse(bits=self.bits[address : address + count])
        return FakeResponse(registers=self.registers[address : address + count])

    async def read_coils(self, address: int, *, count: int, device_id: int) -> Any:
        return self._response("coil", address, count)

    async def read_discrete_inputs(self, address: int, *, count: int, device_id: int) -> Any:
        return self._response("discrete_input", address, count)

    async def read_holding_registers(self, address: int, *, count: int, device_id: int) -> Any:
        return self._response("holding_register", address, count)

    async def read_input_registers(self, address: int, *, count: int, device_id: int) -> Any:
        return self._response("input_register", address, count)


def _map() -> PointMap:
    return PointMap.model_validate(
        {
            "version": 1,
            "source": {
                "id": "test-source",
                "type": "modbus_tcp",
                "host": "127.0.0.1",
                "port": 5020,
                "slaves": [
                    {
                        "unit_id": 1,
                        "device_id": "inv-01",
                        "points": [
                            {
                                "metric": "ac_power_kw",
                                "function": "holding_register",
                                "address": 100,
                                "type": "float32",
                                "unit": "kW",
                            },
                            {
                                "metric": "temperature_c",
                                "function": "holding_register",
                                "address": 102,
                                "type": "int16",
                                "scale": 0.1,
                                "unit": "degC",
                            },
                            {
                                "metric": "running",
                                "function": "coil",
                                "address": 0,
                                "type": "bool",
                            },
                        ],
                    }
                ],
            },
        }
    )


def _float_words(value: float) -> list[int]:
    raw = struct.pack(">f", value)
    return [int.from_bytes(raw[:2], "big"), int.from_bytes(raw[2:], "big")]


async def test_poll_reads_blocks_decodes_and_emits() -> None:
    emitted: list[Sample] = []
    source = ModbusTcpSource(_map(), emitted.append)
    fake = FakeClient()
    fake.registers[100:102] = _float_words(123.4)
    fake.registers[102] = 253
    fake.bits[0] = True
    source._client = fake

    samples = await source.poll_once()

    assert [sample.metric for sample in samples] == [
        "running",
        "ac_power_kw",
        "temperature_c",
    ]
    by_metric = {sample.metric: sample for sample in samples}
    assert by_metric["ac_power_kw"].value == pytest.approx(123.4)
    assert by_metric["temperature_c"].value == pytest.approx(25.3)
    assert by_metric["running"].value is True
    assert by_metric["ac_power_kw"].source == SourceKind.MODBUS
    assert by_metric["ac_power_kw"].quality == Quality.GOOD
    assert emitted == samples
    assert fake.calls == [
        ("coil", 0, 1, 0),
        ("holding_register", 100, 3, 0),
    ]


async def test_timeout_emits_bad_quality_and_counts_error() -> None:
    emitted: list[Sample] = []
    source = ModbusTcpSource(_map(), emitted.append)
    fake = FakeClient()
    fake.raise_on_read = True
    source._client = fake

    samples = await source.poll_once()

    assert len(samples) == 3
    assert all(sample.quality == Quality.BAD for sample in samples)
    assert source.stats.parse_errors == 2
    assert len(emitted) == 3
    assert all("error" in sample.tags for sample in samples)


async def test_modbus_surrogate_config_loads() -> None:
    cfg = load_config("config/collector-modbus-surrogate.yaml")
    assert cfg.sources.modbus_tcp.enabled
    assert cfg.sources.synthetic.enabled is False
    assert cfg.sources.modbus_tcp.point_map.endswith("solar-surrogate.yaml")


async def test_source_name_contains_source_id() -> None:
    source = ModbusTcpSource(_map(), lambda sample: None)
    assert source.name == "modbus_tcp:test-source"
