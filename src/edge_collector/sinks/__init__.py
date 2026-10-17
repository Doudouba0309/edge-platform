"""Sink implementations and the transport contract."""

from __future__ import annotations

from edge_collector.sinks.base import Sink, SinkStats, SinkUnavailable
from edge_collector.sinks.greengrass import GreengrassIpcSink
from edge_collector.sinks.log import LogSink
from edge_collector.sinks.mqtt import MqttSink

__all__ = [
    "GreengrassIpcSink",
    "LogSink",
    "MqttSink",
    "Sink",
    "SinkStats",
    "SinkUnavailable",
]
