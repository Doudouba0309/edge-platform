"""AWS IoT Greengrass V2 IPC sink.

When the collector runs as a Greengrass component it should not hold IoT Core
credentials or open its own TLS session. It hands a batch to the nucleus over the
local IPC socket; the nucleus owns the device certificate, the IoT Core
connection and its offline queue::

    collector component --IPC--> nucleus --mTLS--> AWS IoT Core

A nucleus that is not up yet is transient: ``start`` logs and returns, and the
pipeline spools while the sink retries at a bounded rate. A missing SDK is
permanent and fails fast, because retrying cannot fix it.

The IPC client comes from the optional AWS IoT Device SDK extra::

    uv sync --extra aws
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from edge_collector.config import GreengrassSinkConfig
from edge_collector.models import Batch
from edge_collector.sinks.base import Sink, SinkUnavailable
from edge_collector.topics import status_topic, telemetry_topic

log = logging.getLogger(__name__)

SOCKET_ENV_VAR = "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT"

_AUTH_MARKERS = (
    "unauthoriz",
    "not authorized",
    "accessdenied",
    "access denied",
    "forbidden",
)


def authorization_hint(exc: Exception) -> str:
    """Turn an IPC authorization failure into an actionable suggestion."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if not any(marker in text for marker in _AUTH_MARKERS):
        return ""
    return (
        " This looks like an authorization failure. Check the component recipe's "
        "accessControl entry: the operation and its topic resources must both "
        "allow this publish. Resources are topic strings, not ARNs."
    )


class GreengrassIpcSink(Sink):
    kind = "greengrass"
    supports_status = True

    def __init__(self, cfg: GreengrassSinkConfig, *, gateway_id: str) -> None:
        super().__init__()
        self.cfg = cfg
        self.gateway_id = gateway_id
        self._ipc: Any = None
        self._qos: Any = None
        self._last_error: str | None = None
        self._next_attempt_at = 0.0

    @property
    def name(self) -> str:
        return "greengrass-ipc"

    @property
    def healthy(self) -> bool:
        return self._ipc is not None

    async def start(self) -> None:
        self._next_attempt_at = 0.0
        await self._connect_if_due()
        if self._ipc is None:
            log.warning(
                "greengrass ipc is not reachable yet (%s); batches will spool "
                "and retry every %.0fs",
                self._last_error,
                self.cfg.reconnect_interval_s,
            )

    async def _connect_if_due(self) -> None:
        now = time.monotonic()
        if self._ipc is not None or now < self._next_attempt_at:
            return
        self._next_attempt_at = now + self.cfg.reconnect_interval_s
        await self._connect()

    async def _connect(self) -> bool:
        try:
            from awsiot.greengrasscoreipc.clientv2 import GreengrassCoreIPCClientV2
            from awsiot.greengrasscoreipc.model import QOS
        except ImportError as exc:
            raise SinkUnavailable(
                "greengrass IPC sink requires awsiotsdk; install the 'aws' extra"
            ) from exc

        self._qos = QOS.AT_LEAST_ONCE if self.cfg.qos == 1 else QOS.AT_MOST_ONCE
        # The SDK reads the socket path from the environment, not a parameter.
        os.environ[SOCKET_ENV_VAR] = self.cfg.ipc_socket

        try:
            self._ipc = await asyncio.wait_for(
                asyncio.to_thread(GreengrassCoreIPCClientV2),
                timeout=self.cfg.timeout_s,
            )
        except Exception as exc:
            self._ipc = None
            self._last_error = f"{type(exc).__name__}: {exc}"
            return False

        self._last_error = None
        log.info("greengrass ipc sink ready (socket=%s)", self.cfg.ipc_socket)
        return True

    async def send(self, batch: Batch) -> None:
        if self._ipc is None:
            await self._connect_if_due()
            if self._ipc is None:
                raise SinkUnavailable(f"greengrass ipc unavailable ({self._last_error})")

        payload = batch.to_json()
        topic = telemetry_topic(batch.gateway_id, batch.device_id)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._publish, topic, payload),
                timeout=self.cfg.timeout_s,
            )
        except TimeoutError as exc:
            self.stats.failed += 1
            self.stats.last_error = "ipc publish timed out"
            self._schedule_reconnect()
            raise SinkUnavailable(
                f"greengrass ipc publish timed out after {self.cfg.timeout_s}s"
            ) from exc
        except SinkUnavailable:
            self.stats.failed += 1
            raise
        except Exception as exc:
            self.stats.failed += 1
            self.stats.last_error = str(exc)
            self._schedule_reconnect()
            hint = authorization_hint(exc)
            if hint:
                log.error("greengrass ipc publish failed: %s.%s", exc, hint)
            raise SinkUnavailable(f"greengrass ipc publish failed: {exc}{hint}") from exc

        self.stats.sent += 1
        self.stats.bytes_sent += len(payload)
        self.stats.last_error = None
        log.debug("greengrass: published %d samples to %s", len(batch.samples), topic)

    def _schedule_reconnect(self) -> None:
        self._ipc = None
        self._last_error = self.stats.last_error or "publish failed"
        self._next_attempt_at = time.monotonic() + self.cfg.reconnect_interval_s

    async def publish_status(self, payload: bytes) -> None:
        """Publish presence/heartbeat through the nucleus (best effort)."""
        if self._ipc is None:
            await self._connect_if_due()
            if self._ipc is None:
                raise SinkUnavailable(f"greengrass ipc unavailable ({self._last_error})")
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._publish, status_topic(self.gateway_id), payload),
                timeout=self.cfg.timeout_s,
            )
        except Exception as exc:
            log.warning("greengrass status publish failed: %s", exc)
            raise SinkUnavailable(f"greengrass status publish failed: {exc}") from exc

    def _publish(self, topic: str, payload: bytes) -> None:
        self._ipc.publish_to_iot_core(
            topic_name=topic,
            qos=self._qos,
            payload=payload,
        )

    async def stop(self) -> None:
        ipc, self._ipc = self._ipc, None
        self._last_error = None
        if ipc is None:
            return
        close = getattr(ipc, "close", None)
        if not callable(close):
            return
        try:
            await asyncio.to_thread(close)
        except Exception as exc:  # pragma: no cover - best effort teardown
            log.debug("greengrass ipc close failed: %s", exc)
