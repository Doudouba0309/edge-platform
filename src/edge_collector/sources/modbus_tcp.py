"""Modbus TCP source driven by a versioned point map.

The source is deliberately small: read contiguous blocks, decode values into
:class:`Sample`, and report bad quality when a device does not answer. It does
not batch, spool or publish; the pipeline owns those concerns.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import Callable
from typing import Any, Protocol, cast

from pymodbus.client import AsyncModbusTcpClient

from edge_collector.models import Quality, Sample, SourceKind, utcnow
from edge_collector.pointmap import Point, PointMap, Slave
from edge_collector.sources import EmitFn
from edge_collector.sources.base import Source

log = logging.getLogger(__name__)


class ModbusClient(Protocol):
    async def connect(self) -> bool: ...

    def close(self) -> None: ...

    async def read_coils(self, address: int, *, count: int, device_id: int) -> Any: ...

    async def read_discrete_inputs(self, address: int, *, count: int, device_id: int) -> Any: ...

    async def read_holding_registers(self, address: int, *, count: int, device_id: int) -> Any: ...

    async def read_input_registers(self, address: int, *, count: int, device_id: int) -> Any: ...


ClientFactory = Callable[..., ModbusClient]


class ModbusTcpSource(Source):
    """One Modbus TCP connection and its slaves."""

    kind = SourceKind.MODBUS

    def __init__(
        self,
        point_map: PointMap,
        emit: EmitFn,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        super().__init__(emit)
        self.point_map = point_map
        self._client_factory: ClientFactory = client_factory or cast(
            ClientFactory, AsyncModbusTcpClient
        )
        self._client: ModbusClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def name(self) -> str:
        return f"modbus_tcp:{self.point_map.source.id}"

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name=f"source-{self.name}")

    async def stop(self) -> None:
        self._stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("modbus source stopped with an error")
        await self.close()
        self.stats.connected = False

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()

    async def _run(self) -> None:
        source = self.point_map.source
        try:
            while not self._stopping:
                if self._client is None:
                    self._client = self._client_factory(
                        host=source.host,
                        port=source.port,
                        timeout=source.timeout_s,
                        retries=source.retries,
                    )
                connected = await self._client.connect()
                if not connected:
                    self.stats.connected = False
                    self.stats.reconnects += 1
                    log.warning(
                        "modbus %s:%s is not reachable; retrying",
                        source.host,
                        source.port,
                    )
                    await self.close()
                    await asyncio.sleep(min(30.0, source.poll_interval_s))
                    continue

                self.stats.connected = True
                try:
                    await self.poll_once()
                except Exception:
                    self.stats.connected = False
                    log.exception("modbus poll failed for %s", source.id)
                    await self.close()
                    await asyncio.sleep(min(30.0, source.poll_interval_s))
                    continue

                await asyncio.sleep(source.poll_interval_s)
        except asyncio.CancelledError:
            raise
        finally:
            self.stats.connected = False
            await self.close()

    async def poll_once(self) -> list[Sample]:
        """Poll every slave once and emit samples. Public for deterministic tests."""
        client = self._client
        if client is None:
            raise RuntimeError("modbus client is not connected")
        samples: list[Sample] = []
        for slave in self.point_map.source.slaves:
            samples.extend(await self._poll_slave(client, slave))
        for sample in samples:
            self._emit(sample)
        return samples

    async def _poll_slave(self, client: ModbusClient, slave: Slave) -> list[Sample]:
        samples: list[Sample] = []
        for function, points in _group_points(slave.points).items():
            start = min(point.address for point in points)
            end = max(point.address + _width(point) - 1 for point in points)
            count = end - start + 1
            try:
                response = await _read(client, function, start, count, slave.unit_id)
                if response.isError():
                    raise ValueError(f"Modbus exception response: {response}")
                values = _values_from_response(function, response)
            except Exception as exc:
                self.stats.parse_errors += 1
                log.warning(
                    "modbus read failed unit=%s function=%s address=%s count=%s: %s",
                    slave.unit_id,
                    function,
                    start,
                    count,
                    exc,
                )
                for point in points:
                    samples.append(self._bad_sample(slave, point, f"read failed: {exc}"))
                continue

            for point in points:
                try:
                    value = _decode_point(
                        point, values[point.address - start : point.address - start + _width(point)]
                    )
                except Exception as exc:
                    self.stats.parse_errors += 1
                    samples.append(self._bad_sample(slave, point, f"decode failed: {exc}"))
                    continue
                samples.append(
                    Sample(
                        device_id=slave.device_id,
                        metric=point.metric,
                        value=value,
                        ts=utcnow(),
                        source=SourceKind.MODBUS,
                        origin=self._origin(slave, point),
                        unit=point.unit,
                        quality=Quality.GOOD,
                    )
                )
                self._record()

        return samples

    def _bad_sample(self, slave: Slave, point: Point, reason: str) -> Sample:
        if point.type == "bool":
            value: float | int | str | bool = False
        elif point.type == "string":
            value = ""
        else:
            value = 0.0
        self._record()
        return Sample(
            device_id=slave.device_id,
            metric=point.metric,
            value=value,
            ts=utcnow(),
            source=SourceKind.MODBUS,
            origin=self._origin(slave, point),
            unit=point.unit,
            quality=Quality.BAD,
            tags={"error": reason[:120]},
        )

    def _origin(self, slave: Slave, point: Point) -> str:
        source = self.point_map.source
        return f"modbus://{source.host}:{source.port}/unit-{slave.unit_id}/{point.function}:{point.address}"


def _width(point: Point) -> int:
    if point.function in ("coil", "discrete_input"):
        return 1
    if point.type in ("int16", "uint16"):
        return 1
    if point.type in ("int32", "uint32", "float32"):
        return 2
    if point.type == "float64":
        return 4
    if point.type == "string":
        if point.length is None:
            raise ValueError("string point has no length")
        return point.length
    raise ValueError(f"unsupported point type: {point.type}")


def _group_points(points: list[Point]) -> dict[str, list[Point]]:
    grouped: dict[str, list[Point]] = {}
    for point in sorted(points, key=lambda item: (item.function, item.address)):
        grouped.setdefault(point.function, []).append(point)
    return grouped


async def _read(
    client: ModbusClient,
    function: str,
    address: int,
    count: int,
    unit_id: int,
) -> Any:
    if function == "coil":
        return await client.read_coils(address, count=count, device_id=unit_id)
    if function == "discrete_input":
        return await client.read_discrete_inputs(address, count=count, device_id=unit_id)
    if function == "holding_register":
        return await client.read_holding_registers(address, count=count, device_id=unit_id)
    if function == "input_register":
        return await client.read_input_registers(address, count=count, device_id=unit_id)
    raise ValueError(f"unknown Modbus function: {function}")


def _values_from_response(function: str, response: Any) -> list[int | bool]:
    if function in ("coil", "discrete_input"):
        return list(response.bits)
    return list(response.registers)


def _decode_point(point: Point, values: list[int | bool]) -> float | int | str | bool:
    if point.function in ("coil", "discrete_input"):
        return bool(values[0])

    raw_registers = [int(value) for value in values]
    if point.type == "string":
        data = _registers_to_bytes(raw_registers, point.byte_order)
        return data.decode("utf-8", errors="replace").rstrip("\x00")

    if len(raw_registers) == 1:
        data = _registers_to_bytes(raw_registers, point.byte_order)
        if point.type == "int16":
            raw: float | int = struct.unpack(">h", data)[0]
        elif point.type == "uint16":
            raw = struct.unpack(">H", data)[0]
        else:
            raise ValueError(f"unsupported 16-bit type: {point.type}")
    else:
        words = raw_registers if point.word_order == "big" else list(reversed(raw_registers))
        data = _registers_to_bytes(words, point.byte_order)
        if point.type == "int32":
            raw = struct.unpack(">i", data)[0]
        elif point.type == "uint32":
            raw = struct.unpack(">I", data)[0]
        elif point.type == "float32":
            raw = struct.unpack(">f", data)[0]
        elif point.type == "float64":
            raw = struct.unpack(">d", data)[0]
        else:
            raise ValueError(f"unsupported register type: {point.type}")

    value = raw * point.scale + point.offset
    if (
        point.scale == 1.0
        and point.offset == 0.0
        and point.type
        in (
            "int16",
            "uint16",
            "int32",
            "uint32",
        )
    ):
        return int(value)
    return float(value)


def _registers_to_bytes(registers: list[int], byte_order: str) -> bytes:
    data = b"".join(register.to_bytes(2, "big") for register in registers)
    if byte_order == "little":
        data = b"".join(
            bytes(reversed(data[index : index + 2])) for index in range(0, len(data), 2)
        )
    return data
