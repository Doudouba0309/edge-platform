"""Transport extension point.

A sink only moves a complete :class:`~edge_collector.models.Batch`. It must never
inspect where a sample came from, and it signals "buffer it" by raising
:class:`SinkUnavailable` rather than blocking or swallowing the failure.
"""

from __future__ import annotations

from typing import Protocol

from edge_collector.models import Batch


class SinkUnavailable(RuntimeError):
    """The transport is down; the pipeline should buffer or retry."""


class Sink(Protocol):
    async def send(self, batch: Batch) -> None:
        """Deliver one batch, or raise :class:`SinkUnavailable`."""
