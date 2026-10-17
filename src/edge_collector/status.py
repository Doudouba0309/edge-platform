"""Gateway presence and heartbeat.

Status is deliberately separate from telemetry. It tells an operator whether the
gateway is alive and healthy even when no batch is due, and it works through
either the MQTT sink or the Greengrass IPC sink.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from edge_collector.models import utcnow
from edge_collector.sinks import Sink

log = logging.getLogger(__name__)

SnapshotFn = Callable[[], dict[str, object]]


def collector_version() -> str:
    try:
        return version("edge-collector")
    except PackageNotFoundError:
        return "unknown"


class StatusReporter:
    def __init__(
        self,
        *,
        gateway_id: str,
        sink: Sink,
        snapshot: SnapshotFn,
        interval_s: float = 30.0,
        enabled: bool = True,
        component_version: str = "dev",
    ) -> None:
        self.gateway_id = gateway_id
        self.sink = sink
        self.snapshot = snapshot
        self.interval_s = interval_s
        self.enabled = enabled
        self.component_version = component_version
        self.sent = 0
        self.failed = 0
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._started_at: float | None = None
        self._started = False

    async def start(self) -> None:
        if not self.enabled or not self.sink.supports_status or self._task is not None:
            return
        self._started_at = time.monotonic()
        self._started = True
        await self._publish(state="online", event="online")
        self._task = asyncio.create_task(self._loop(), name="status-heartbeat")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._started:
            await self._publish(state="offline", event="offline")
            self._started = False

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            await self._publish(state="online", event="heartbeat")

    async def _publish(self, *, state: str, event: str) -> None:
        if not self.sink.supports_status:
            return
        snapshot = self.snapshot()
        now = utcnow()
        stale_after_s = self.interval_s * 3
        sources = snapshot.get("sources", {})
        source_health: dict[str, Any] = {}
        if isinstance(sources, dict):
            for name, value in sources.items():
                if isinstance(value, dict):
                    source_health[str(name)] = bool(value.get("connected"))
        sink = snapshot.get("sink", {})
        payload = {
            "gateway_id": self.gateway_id,
            "state": state,
            "event": event,
            "ts": now.isoformat(),
            "version": self.component_version,
            "package_version": collector_version(),
            "heartbeat_interval_s": self.interval_s,
            "stale_after_s": stale_after_s,
            "expires_at": (now + timedelta(seconds=stale_after_s)).isoformat(),
            "uptime_s": round(time.monotonic() - (self._started_at or time.monotonic()), 1),
            "ready": bool(snapshot.get("ready")),
            "spool_pending": snapshot.get("spool_pending", 0),
            "sources": source_health,
            "sink": {
                "name": sink.get("name") if isinstance(sink, dict) else None,
                "healthy": bool(sink.get("healthy")) if isinstance(sink, dict) else False,
            },
            "last_error": snapshot.get("last_error"),
        }
        try:
            await self.sink.publish_status(
                json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
            )
        except Exception as exc:
            self.failed += 1
            self.last_error = str(exc)
            log.warning("status publish failed (%s): %s", event, exc)
        else:
            self.sent += 1
            self.last_error = None
