"""Stdlib health endpoint."""

from __future__ import annotations

import asyncio
import json

from edge_collector.config import HealthConfig
from edge_collector.health import HealthServer


async def _get(port: int, path: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    writer.write(request.encode())
    await writer.drain()
    data = await reader.read()
    writer.close()
    await writer.wait_closed()
    return data


def _status(response: bytes) -> int:
    return int(response.split(b" ", 2)[1])


def _body(response: bytes) -> bytes:
    return response.split(b"\r\n\r\n", 1)[1]


async def test_healthz_is_always_ok() -> None:
    server = HealthServer(
        HealthConfig(host="127.0.0.1", port=0),
        lambda: {"ready": False},
    )
    await server.start()
    assert server.port is not None

    response = await _get(server.port, "/healthz")
    assert _status(response) == 200
    assert _body(response) == b"ok\n"

    await server.stop()


async def test_root_is_an_alias_for_healthz() -> None:
    server = HealthServer(HealthConfig(host="127.0.0.1", port=0), lambda: {})
    await server.start()
    assert server.port is not None

    response = await _get(server.port, "/")
    assert _status(response) == 200

    await server.stop()


async def test_readyz_is_200_when_ready() -> None:
    server = HealthServer(
        HealthConfig(host="127.0.0.1", port=0),
        lambda: {"ready": True, "accepted": 3},
    )
    await server.start()
    assert server.port is not None

    response = await _get(server.port, "/readyz")
    assert _status(response) == 200
    assert _body(response) == b"ready\n"

    await server.stop()


async def test_readyz_is_503_when_not_ready() -> None:
    server = HealthServer(
        HealthConfig(host="127.0.0.1", port=0),
        lambda: {"ready": False},
    )
    await server.start()
    assert server.port is not None

    response = await _get(server.port, "/readyz")
    assert _status(response) == 503
    assert _body(response) == b"not ready\n"

    await server.stop()


async def test_stats_returns_json() -> None:
    state = {
        "ready": True,
        "accepted": 4,
        "sources": {"synthetic": {"connected": True}},
    }
    server = HealthServer(
        HealthConfig(host="127.0.0.1", port=0),
        lambda: state,
    )
    await server.start()
    assert server.port is not None

    response = await _get(server.port, "/stats")
    assert _status(response) == 200
    assert json.loads(_body(response)) == state

    await server.stop()


async def test_unknown_path_is_404() -> None:
    server = HealthServer(HealthConfig(host="127.0.0.1", port=0), lambda: {})
    await server.start()
    assert server.port is not None

    response = await _get(server.port, "/nope")
    assert _status(response) == 404

    await server.stop()


async def test_disabled_server_binds_nothing() -> None:
    server = HealthServer(HealthConfig(enabled=False), lambda: {})
    await server.start()
    assert server.port is None
    await server.stop()


async def test_stop_is_idempotent() -> None:
    server = HealthServer(HealthConfig(host="127.0.0.1", port=0), lambda: {})
    await server.start()
    await server.stop()
    await server.stop()
    assert server.port is None
