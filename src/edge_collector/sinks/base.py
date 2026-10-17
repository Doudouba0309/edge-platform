"""Sink interface and transport counters.

A sink owns exactly one transport. The pipeline treats them identically, which
is what lets the same collector publish to a local Mosquitto broker in
development and to a site broker in production, changed only by configuration.

Contract: ``send`` raises :class:`SinkUnavailable` when the transport is down so
the pipeline can buffer the batch instead of losing it.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import ClassVar

from edge_collector.models import Batch


class SinkUnavailable(RuntimeError):
    """Transport is not currently usable (offline, not connected, throttled)."""


@dataclass
class SinkStats:
    sent: int = 0
    failed: int = 0
    bytes_sent: int = 0
    last_error: str | None = None


class Sink(abc.ABC):
    kind: ClassVar[str]

    def __init__(self) -> None:
        self.stats = SinkStats()

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short identifier used in logs and health output."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Acquire the transport. Should raise if it cannot be used at all."""

    @abc.abstractmethod
    async def send(self, batch: Batch) -> None:
        """Publish one batch, or raise SinkUnavailable to trigger buffering."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Release the transport. Must be idempotent."""

    @property
    def healthy(self) -> bool:
        return self.stats.last_error is None
