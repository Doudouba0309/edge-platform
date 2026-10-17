"""Log sink: the offline sink used by development runs and smoke tests."""

from __future__ import annotations

import logging

from edge_collector.models import Batch
from edge_collector.sinks.base import Sink

log = logging.getLogger(__name__)


class LogSink(Sink):
    kind = "log"

    @property
    def name(self) -> str:
        return "log"

    async def start(self) -> None:
        log.info("log sink ready")

    async def send(self, batch: Batch) -> None:
        payload = batch.to_json()
        self.stats.sent += 1
        self.stats.bytes_sent += len(payload)
        log.info(
            "batch #%d device=%s samples=%d bytes=%d sources=%s",
            batch.seq,
            batch.device_id,
            len(batch.samples),
            len(payload),
            sorted({sample.source.value for sample in batch.samples}),
        )

    async def stop(self) -> None:
        return
