import asyncio
import json

from edge_collector.sinks.base import Sink
from edge_collector.status import StatusReporter


class FakeStatusSink(Sink):
    kind = "fake"
    supports_status = True

    def __init__(self) -> None:
        super().__init__()
        self.statuses: list[bytes] = []

    @property
    def name(self) -> str:
        return "fake"

    async def start(self) -> None:
        return None

    async def send(self, batch) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish_status(self, payload: bytes) -> None:
        self.statuses.append(payload)


def _snapshot() -> dict[str, object]:
    return {
        "ready": True,
        "sources": {"synthetic": {"connected": True}},
        "sink": {"name": "fake", "healthy": True},
        "spool_pending": 0,
        "last_error": None,
    }


async def test_status_reporter_publishes_online_heartbeat_and_offline() -> None:
    sink = FakeStatusSink()
    reporter = StatusReporter(
        gateway_id="gw-status",
        sink=sink,
        snapshot=_snapshot,
        interval_s=0.01,
    )

    await reporter.start()
    await asyncio.sleep(0.03)
    await reporter.stop()

    payloads = [json.loads(item) for item in sink.statuses]
    assert payloads[0]["state"] == "online"
    assert payloads[0]["event"] == "online"
    assert any(item["event"] == "heartbeat" for item in payloads)
    assert payloads[-1]["state"] == "offline"
    assert payloads[-1]["event"] == "offline"
    assert payloads[0]["gateway_id"] == "gw-status"
    assert payloads[0]["ready"] is True
    assert "version" in payloads[0]


async def test_status_reporter_is_noop_for_sink_without_status() -> None:
    sink = FakeStatusSink()
    sink.supports_status = False
    reporter = StatusReporter(
        gateway_id="gw-status",
        sink=sink,
        snapshot=_snapshot,
        interval_s=0.01,
    )

    await reporter.start()
    await reporter.stop()
    assert sink.statuses == []
