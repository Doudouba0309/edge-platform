"""Sink implementations and the transport contract."""

from __future__ import annotations

from edge_collector.sinks.base import Sink, SinkUnavailable
from edge_collector.sinks.log import LogSink

__all__ = ["LogSink", "Sink", "SinkUnavailable"]
