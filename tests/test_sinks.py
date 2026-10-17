"""Sink contract, MQTT topic selection and TLS configuration."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from edge_collector.config import ConfigError, GreengrassSinkConfig, MqttSinkConfig
from edge_collector.sinks import (
    GreengrassIpcSink,
    LogSink,
    MqttSink,
    SinkUnavailable,
)
from edge_collector.sinks.greengrass import authorization_hint


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


class FakeIpc:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def publish_to_iot_core(self, **kwargs: object) -> None:
        self.calls.append(kwargs)

    def close(self) -> None:
        self.closed = True


async def test_greengrass_sink_publishes_through_the_fake_ipc(make_batch) -> None:
    sink = GreengrassIpcSink(
        GreengrassSinkConfig(ipc_socket="/tmp/greengrass-test.sock"),
        gateway_id="dev-gateway-01",
    )
    fake = FakeIpc()
    sink._ipc = fake
    sink._qos = "AT_LEAST_ONCE"

    batch = make_batch(gateway_id="dev-gateway-01")
    await sink.send(batch)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["topic_name"] == "edge/dev-gateway-01/plc-line-1/telemetry"
    assert call["qos"] == "AT_LEAST_ONCE"
    payload = json.loads(call["payload"])  # type: ignore[arg-type]
    assert payload["gateway_id"] == "dev-gateway-01"
    assert sink.stats.sent == 1
    assert sink.stats.bytes_sent > 0
    assert sink.healthy

    await sink.stop()
    assert fake.closed
    assert not sink.healthy


async def test_greengrass_sink_degrades_when_ipc_is_unavailable(make_batch, monkeypatch) -> None:
    sink = GreengrassIpcSink(GreengrassSinkConfig(), gateway_id="dev-gateway-01")

    async def no_connect() -> None:
        return None

    monkeypatch.setattr(sink, "_connect_if_due", no_connect)
    with pytest.raises(SinkUnavailable, match="greengrass ipc unavailable"):
        await sink.send(make_batch())


def test_authorization_hint_recognises_ipc_denials() -> None:
    hint = authorization_hint(RuntimeError("AccessDeniedException: not authorized"))
    assert "accessControl" in hint
    assert "topic strings" in hint
    assert authorization_hint(RuntimeError("socket closed")) == ""


async def test_greengrass_sink_publishes_status(make_batch) -> None:
    sink = GreengrassIpcSink(
        GreengrassSinkConfig(ipc_socket="/tmp/greengrass-test.sock"),
        gateway_id="dev-gateway-01",
    )
    fake = FakeIpc()
    sink._ipc = fake
    sink._qos = "AT_LEAST_ONCE"

    await sink.publish_status(b'{"state":"online"}')

    assert fake.calls[0]["topic_name"] == "edge/dev-gateway-01/status"
    assert fake.calls[0]["payload"] == b'{"state":"online"}'


def test_mqtt_sink_uses_json_last_will() -> None:
    sink = MqttSink(MqttSinkConfig(), gateway_id="dev-gateway-01")
    assert sink._will is not None
    payload = json.loads(sink._will[1])
    assert payload["state"] == "offline"
    assert payload["event"] == "lwt"
    assert payload["gateway_id"] == "dev-gateway-01"


def test_mqtt_sink_rejects_client_id_mismatch_for_iot_core() -> None:
    with pytest.raises(ConfigError):
        MqttSink(
            MqttSinkConfig(
                host="example-ats.iot.ap-southeast-1.amazonaws.com",
                client_id="not-the-thing",
            ),
            gateway_id="edge-platform-sandbox-core",
        )
