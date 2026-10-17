"""Shared paho-mqtt plumbing for MQTT transports.

paho is synchronous and thread-based. It owns a network thread via
``loop_start()``; the asyncio loop only waits for connection and publish
confirmation, so a stalled broker cannot freeze ingestion.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
import threading
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from edge_collector.models import Batch
from edge_collector.sinks.base import Sink, SinkUnavailable

log = logging.getLogger(__name__)


class PahoSink(Sink):
    """Connection state, Last Will, TLS and publish confirmation."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: str,
        qos: int,
        keepalive_s: int,
        connect_timeout_s: float,
        publish_timeout_s: float,
        will: tuple[str, bytes, int, bool] | None = None,
        ca_file: str | None = None,
        cert_file: str | None = None,
        key_file: str | None = None,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.qos = qos
        self._client_id = client_id
        self._keepalive_s = keepalive_s
        self._connect_timeout_s = connect_timeout_s
        self._publish_timeout_s = publish_timeout_s
        self._will = will
        self._status_topic = will[0] if will else None
        self._ca_file = ca_file
        self._cert_file = cert_file
        self._key_file = key_file
        self._client: mqtt.Client | None = None
        self._connected = threading.Event()

    # ------------------------------------------------------------- overrides #
    def _configure_client(self, client: mqtt.Client) -> None:
        """Hook for credentials and TLS before connecting."""

    def topic_for(self, batch: Batch) -> str:
        raise NotImplementedError

    # -------------------------------------------------------------- lifecycle #
    async def start(self) -> None:
        if self._client is not None:
            return

        client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
            protocol=mqtt.MQTTv311,
        )
        if self._will is not None:
            topic, payload, qos, retain = self._will
            client.will_set(topic, payload, qos=qos, retain=retain)
        if self._ca_file is not None:
            client.tls_set(
                ca_certs=self._ca_file,
                certfile=self._cert_file,
                keyfile=self._key_file,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            client.tls_insecure_set(False)
        self._configure_client(client)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client = client

        client.connect_async(self.host, self.port, keepalive=self._keepalive_s)
        client.loop_start()
        connected = await asyncio.to_thread(
            self._connected.wait, self._connect_timeout_s
        )
        if connected:
            log.info("%s: connected to %s:%d", self.name, self.host, self.port)
        else:
            # Not fatal: paho keeps retrying and the pipeline spools meanwhile.
            log.warning(
                "%s: not connected to %s:%d yet; paho will retry",
                self.name,
                self.host,
                self.port,
            )

    async def stop(self) -> None:
        client, self._client = self._client, None
        self._connected.clear()
        if client is not None:
            with contextlib.suppress(Exception):
                client.disconnect()
            with contextlib.suppress(Exception):
                client.loop_stop()
            log.info("%s: stopped", self.name)

    # ---------------------------------------------------------------- publish #
    async def announce(self, state: bytes) -> None:
        """Publish retained gateway presence on the status topic."""
        client = self._client
        if client is None or self._status_topic is None or not self._connected.is_set():
            return
        try:
            info = client.publish(self._status_topic, state, qos=1, retain=True)
            await asyncio.to_thread(info.wait_for_publish, self._publish_timeout_s)
        except Exception as exc:  # pragma: no cover - best effort
            log.debug("%s: status announce failed: %s", self.name, exc)

    async def send(self, batch: Batch) -> None:
        client = self._client
        if client is None:
            raise SinkUnavailable(f"{self.name}: not started")
        if not self._connected.is_set():
            raise SinkUnavailable(
                f"{self.name}: not connected to {self.host}:{self.port}"
            )

        payload = batch.to_json()
        topic = self.topic_for(batch)
        try:
            info = client.publish(topic, payload, qos=self.qos)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise SinkUnavailable(f"{self.name}: publish rejected rc={info.rc}")
            if self.qos > 0:
                await asyncio.to_thread(info.wait_for_publish, self._publish_timeout_s)
                if not info.is_published():
                    raise SinkUnavailable(
                        f"{self.name}: publish confirmation timed out"
                    )
        except SinkUnavailable as exc:
            self.stats.failed += 1
            self.stats.last_error = str(exc)
            raise
        except Exception as exc:
            self.stats.failed += 1
            self.stats.last_error = str(exc)
            raise SinkUnavailable(f"{self.name}: {exc}") from exc

        self.stats.sent += 1
        self.stats.bytes_sent += len(payload)
        self.stats.last_error = None

    # -------------------------------------------------------------- callbacks #
    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any = None,
    ) -> None:
        if reason_code.is_failure:
            self.stats.last_error = f"connect failed: {reason_code}"
            log.error("%s: connect failed: %s", self.name, reason_code)
            return
        self._connected.set()
        self.stats.last_error = None
        if self._status_topic is not None:
            client.publish(self._status_topic, b"online", qos=1, retain=True)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any = None,
    ) -> None:
        self._connected.clear()
        if reason_code.is_failure:
            log.warning(
                "%s: disconnected (%s); paho will retry", self.name, reason_code
            )

    @property
    def healthy(self) -> bool:
        return self._connected.is_set() and self.stats.last_error is None
