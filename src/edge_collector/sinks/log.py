"""Log sink: the offline sink used by development runs and smoke tests."""

from __future__ import annotations

import logging

from edge_collector.models import Batch

log = logging.getLogger(__name__)


class LogSink:
    async def send(self, batch: Batch) -> None:
        payload = batch.to_json()
        log.info(
            "batch #%d device=%s samples=%d bytes=%d sources=%s",
            batch.seq,
            batch.device_id,
            len(batch.samples),
            len(payload),
            sorted({sample.source.value for sample in batch.samples}),
        )
