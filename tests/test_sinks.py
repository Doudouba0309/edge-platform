"""Sink contract, MQTT topic selection and TLS configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from edge_collector.config import MqttSinkConfig
from edge_collector.sinks import LogSink, MqttSink, SinkUnavailable


def _mqtt_config(**overrides: object) -> MqttSinkConfig:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 8883,
        "ca_file": "certs/ca.crt",
        "cert_file": "certs/client.crt",
        "key_file": "certs/client.key",
    }
    values.update(overrides)
    return MqttSinkConfig(**values)  # type: ignore[arg-type]


async def test_log_sink_counts_and_is_healthy(make_batch) -> None:
    sink = LogSink()
    await sink.start()
    await sink.send(make_batch())

    assert sink.name == "log"
    assert sink.healthy
    assert sink.stats.sent == 1
    assert sink.stats.bytes_sent > 0

    await sink.stop()


def test_mqtt_sink_uses_the_frozen_telemetry_topic(make_batch) -> None:
    sink = MqttSink(_mqtt_config(), gateway_id="dev-gateway-01")
    batch = make_batch(gateway_id="dev-gateway-01")
    assert sink.name == "mqtt"
    assert sink.topic_for(batch) == "edge/dev-gateway-01/plc-line-1/telemetry"


def test_mqtt_sink_client_id_defaults_to_gateway_id() -> None:
    sink = MqttSink(_mqtt_config(), gateway_id="dev-gateway-01")
    assert sink._client_id == "dev-gateway-01"


def test_mqtt_sink_is_unhealthy_before_start() -> None:
    sink = MqttSink(_mqtt_config(), gateway_id="dev-gateway-01")
    assert sink.healthy is False


async def test_mqtt_sink_send_before_start_is_unavailable(make_batch) -> None:
    sink = MqttSink(_mqtt_config(), gateway_id="dev-gateway-01")
    with pytest.raises(SinkUnavailable):
        await sink.send(make_batch())


def test_mqtt_tls_files_must_be_all_or_nothing() -> None:
    with pytest.raises(ValidationError):
        MqttSinkConfig(ca_file="certs/ca.crt")


def test_mqtt_config_allows_plain_mqtt() -> None:
    cfg = MqttSinkConfig(host="localhost", port=1883)
    assert cfg.ca_file is None
    assert cfg.cert_file is None
    assert cfg.key_file is None
