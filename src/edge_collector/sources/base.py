"""Source interface and per-source counters."""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import ClassVar

from edge_collector.models import SourceKind
from edge_collector.sources import EmitFn


@dataclass
class SourceStats:
    """Cheap counters surfaced on the health endpoint."""

    received: int = 0
    #: Genuine loss: unusable or unparseable values.
    dropped: int = 0
    #: Suppressed on purpose (for example OPC UA deadband) - NOT lost data.
    filtered: int = 0
    parse_errors: int = 0
    reconnects: int = 0
    connected: bool = False
    last_sample_at: float | None = None
    extra: dict[str, str] = field(default_factory=dict)


class Source(abc.ABC):
    """Base class for every ingest path."""

    kind: ClassVar[SourceKind]

    def __init__(self, emit: EmitFn) -> None:
        self._emit = emit
        self.stats = SourceStats()

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short, stable identifier used in logs and health."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin ingesting. Must return promptly; work happens in a task."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop ingesting and release connections. Must be idempotent."""

    @property
    def healthy(self) -> bool:
        return self.stats.connected

    def _record(self) -> None:
        self.stats.received += 1
        self.stats.last_sample_at = time.time()
