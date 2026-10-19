#!/usr/bin/env python3
"""Local Modbus TCP surrogate for the Phase 1A solar point map.

Values are deterministic and match config/pointmaps/solar-surrogate.yaml.
This is a test bench, not a device simulator for production.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import struct

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer

log = logging.getLogger("modbus-surrogate")


def _f32(value: float) -> list[int]:
    raw = struct.pack(">f", value)
    return [int.from_bytes(raw[0:2], "big"), int.from_bytes(raw[2:4], "big")]


def _f64(value: float) -> list[int]:
    raw = struct.pack(">d", value)
    return [int.from_bytes(raw[index : index + 2], "big") for index in range(0, 8, 2)]


def _registers(size: int = 128) -> list[int]:
    return [0] * size


def _inverter_registers() -> list[int]:
    regs = _registers()
    for address, value in (
        (100, 123.4),  # ac_power_kw
        (102, 130.0),  # dc_power_kw
        (104, 456.7),  # energy_today_kwh
    ):
        regs[address : address + 2] = _f32(value)
    regs[106] = 253  # inverter_temp_c 25.3 C
    regs[108] = 1  # status_code: running
    regs[109] = 0  # fault_code
    return regs


def _meter_registers() -> list[int]:
    regs = _registers()
    regs[10:12] = _f32(100.0)  # export_power_kw
    regs[12:14] = _f32(0.0)  # import_power_kw
    regs[14:18] = _f64(1000.0)  # energy_export_kwh
    return regs


def _weather_registers() -> list[int]:
    regs = _registers()
    regs[0] = 850  # irradiance_w_m2
    regs[2] = 285  # ambient_temp_c 28.5 C
    regs[4] = 32  # wind_speed_m_s 3.2 m/s
    return regs


def build_context() -> ModbusServerContext:
    devices = {
        1: ModbusDeviceContext(hr=ModbusSequentialDataBlock(1, _inverter_registers())),
        2: ModbusDeviceContext(ir=ModbusSequentialDataBlock(1, _meter_registers())),
        3: ModbusDeviceContext(ir=ModbusSequentialDataBlock(1, _weather_registers())),
    }
    return ModbusServerContext(devices=devices, single=False)


async def serve(host: str, port: int) -> None:
    log.info("Modbus TCP surrogate listening on %s:%d", host, port)
    log.info("unit 1 inverter, unit 2 meter, unit 3 weather")
    await StartAsyncTcpServer(build_context(), address=(host, port))


def main() -> int:
    parser = argparse.ArgumentParser(description="Local solar Modbus TCP surrogate")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5020)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
