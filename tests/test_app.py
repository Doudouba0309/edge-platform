"""Wiring, graceful shutdown and the integrated health snapshot."""

from __future__ import annotations

import asyncio
import json

from edge_collector.app import CollectorApp, build_sink, build_source
from edge_collector.config import CollectorConfig, load_config
from edge_collector.sinks import LogSink, MqttSink
from edge_collector.sources.synthetic import SyntheticSource


def _config(*, health_enabled: bool = False, **batching: object) -> CollectorConfig:
    values: dict[str, object] = {
        "max_samples": 2,
        "flush_interval_s": 0.05,
        "queue_max": 100,
    }
    values.update(batching)
    return CollectorConfig.model_validate(
        {
            "gateway_id": "gw-dev-01",
            "batching": values,
            "health": {
                "enabled": health_enabled,
                "host": "127.0.0.1",
                "port": 0,
            },
            "sources": {
                "synthetic": {
                    "enabled": True,
                    "device_id": "plc-line-1",
                    "interval_s": 0.01,
                    "metrics": [
                        {
                            "name": "temperature",
                            "value": 25.0,
                            "step": 0.5,
                            "unit": "degC",
                        }
                    ],
                }
            },
        }
    )


async def _get(port: int, path: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode()
    )
    await writer.drain()
    data = await reader.read()
    writer.close()
    await writer.wait_closed()
    return data


def test_build_source_returns_the_synthetic_source() -> None:
    source = build_source(_config(), lambda sample: None)
    assert isinstance(source, SyntheticSource)
    assert source.name == "synthetic"


def test_build_sink_returns_the_configured_transport() -> None:
    assert isinstance(build_sink(_config()), LogSink)
    assert isinstance(build_sink(load_config("config/collector-smoke.yaml")), MqttSink)


async def test_snapshot_is_not_ready_before_start() -> None:
    app = CollectorApp(_config())
    snapshot = app._snapshot()
    assert snapshot["ready"] is False
    assert snapshot["sources"]["synthetic"]["connected"] is False  # type: ignore[index]
    assert snapshot["sink"]["name"] == "log"  # type: ignore[index]
    assert snapshot["spool"]["enabled"] is False  # type: ignore[index]


async def test_app_runs_and_shuts_down_cleanly() -> None:
    app = CollectorApp(_config())
    task = asyncio.create_task(app.run(handle_signals=False))

    await asyncio.sleep(0.2)
    assert app.sources[0].healthy
    snapshot = app._snapshot()
    assert snapshot["ready"] is True
    assert snapshot["accepted"] > 0  # type: ignore[operator]

    app.request_stop()
    await asyncio.wait_for(task, 5)

    assert not app.sources[0].healthy
    assert app.pipeline.stats.batches_sent >= 1


async def test_shutdown_flushes_samples_that_have_not_reached_a_batch() -> None:
    app = CollectorApp(_config(max_samples=1000, flush_interval_s=10))
    task = asyncio.create_task(app.run(handle_signals=False))

    await asyncio.sleep(0.1)
    app.request_stop()
    await asyncio.wait_for(task, 5)

    assert app.pipeline.stats.accepted >= 1
    assert app.pipeline.stats.batches_sent >= 1


async def test_health_endpoint_reports_ready_while_running() -> None:
    app = CollectorApp(_config(health_enabled=True))
    task = asyncio.create_task(app.run(handle_signals=False))

    await asyncio.sleep(0.2)
    port = app.health.port
    assert port is not None
    response = await _get(port, "/readyz")
    assert b"200 OK" in response
    assert b"ready\n" in response

    stats = await _get(port, "/stats")
    body = json.loads(stats.split(b"\r\n\r\n", 1)[1])
    assert body["ready"] is True
    assert body["sources"]["synthetic"]["connected"] is True

    app.request_stop()
    await asyncio.wait_for(task, 5)
