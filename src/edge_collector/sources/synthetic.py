"""Deterministic synthetic source.

This is deliberately boring: it is the surrogate that lets the runtime and the
smoke harness be tested before any real protocol adapter exists. Values follow
``value + step * tick`` so a test can assert the exact sequence.
"""

from __future__ import annotations

import asyncio
import logging

from edge_collector.config import SyntheticSourceConfig
from edge_collector.models import Quality, Sample, SourceKind, utcnow
from edge_collector.sources import EmitFn
from edge_collector.sources.base import Source

log = logging.getLogger(__name__)


class SyntheticSource(Source):
    kind = SourceKind.SIM

    def __init__(self, cfg: SyntheticSourceConfig, emit: EmitFn) -> None:
        super().__init__(emit)
        self.cfg = cfg
        self._task: asyncio.Task[None] | None = None
        self._tick = 0

    @property
    def name(self) -> str:
        return "synthetic"

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self.stats.connected = True
        self._task = asyncio.create_task(self._run(), name="source-synthetic")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("synthetic source stopped with an error")
        self.stats.connected = False

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.cfg.interval_s)
                self.emit_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("synthetic source failed")
        finally:
            self.stats.connected = False

    def emit_once(self) -> list[Sample]:
        """Emit one sample per configured metric and return them."""
        self._tick += 1
        samples: list[Sample] = []
        for metric in self.cfg.metrics:
            sample = Sample(
                device_id=self.cfg.device_id,
                metric=metric.name,
                value=metric.value + metric.step * self._tick,
                ts=utcnow(),
                source=SourceKind.SIM,
                origin=f"synthetic:{metric.name}",
                unit=metric.unit,
                quality=Quality.GOOD,
            )
            samples.append(sample)
            self._record()

        for sample in samples:
            self._emit(sample)
        return samples
