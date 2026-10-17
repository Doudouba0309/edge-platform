"""MQTT sink over optional mutual TLS."""

from __future__ import annotations

import paho.mqtt.client as mqtt

from edge_collector.config import MqttSinkConfig
from edge_collector.models import Batch
from edge_collector.sinks.paho_sink import PahoSink
from edge_collector.topics import status_topic, telemetry_topic


class MqttSink(PahoSink):
    kind = "mqtt"

    def __init__(self, cfg: MqttSinkConfig, *, gateway_id: str) -> None:
        self.cfg = cfg
        self.gateway_id = gateway_id
        super().__init__(
            host=cfg.host,
            port=cfg.port,
            client_id=cfg.client_id or gateway_id,
            qos=cfg.qos,
            keepalive_s=cfg.keepalive_s,
            connect_timeout_s=cfg.connect_timeout_s,
            publish_timeout_s=cfg.publish_timeout_s,
            will=(status_topic(gateway_id), b"offline", 1, True),
            ca_file=cfg.ca_file,
            cert_file=cfg.cert_file,
            key_file=cfg.key_file,
        )

    @property
    def name(self) -> str:
        return "mqtt"

    def _configure_client(self, client: mqtt.Client) -> None:
        # TLS, when configured, is applied by PahoSink before this hook.
        return

    def topic_for(self, batch: Batch) -> str:
        return telemetry_topic(batch.gateway_id, batch.device_id)

    async def stop(self) -> None:
        if self._connected.is_set():
            await self.announce(b"offline")
        await super().stop()
