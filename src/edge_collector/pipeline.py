"""The ingest -> batch -> deliver pipeline.

Two decisions dominate this file:

* **One bounded queue.** Memory can never grow without limit on a gateway with
  1 GB of RAM. When the queue fills we drop, loudly, using a configurable
  policy.
* **Two flush triggers.** A batch goes out when it reaches ``max_samples`` *or*
  when ``flush_interval_s`` has elapsed, whichever comes first. Latency and
  size both have a hard ceiling.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import cast

from edge_collector.config import BatchingConfig
from edge_collector.models import Batch, Sample
from edge_collector.sinks import Sink

log = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    accepted: int = 0
    dropped_queue_full: int = 0
    dropped_unsendable: int = 0
    send_failures: int = 0
    batches_built: int = 0
    batches_sent: int = 0
    last_error: str | None = None
    last_batch_at: float | None = None
    per_source: dict[str, int] = field(default_factory=dict)


class Pipeline:
    def __init__(self, gateway_id: str, cfg: BatchingConfig, sink: Sink) -> None:
        self.gateway_id = gateway_id
        self.sink = sink
        self.cfg = cfg
        self.stats = PipelineStats()
        self.failed = asyncio.Event()

        self._queue: asyncio.Queue[Sample | object] = asyncio.Queue(
            maxsize=cfg.queue_max
        )
        self._stop_token = object()
        self._buffer: list[Sample] = []
        self._seq = 0
        self._closing = False
        self._consumer_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread_id: int | None = None
        self._last_flush = time.monotonic()

    # ------------------------------------------------------------------ submit #
    def submit(self, sample: Sample) -> None:
        """Thread-safe, non-blocking hand-off. Safe to call from paho threads."""
        if self._closing:
            return
        if self._loop is None or threading.get_ident() == self._thread_id:
            self._enqueue(sample)
        else:
            self._loop.call_soon_threadsafe(self._enqueue, sample)

    def _enqueue(self, sample: Sample) -> None:
        if self._closing:
            return
        try:
            self._queue.put_nowait(sample)
            self.stats.accepted += 1
        except asyncio.QueueFull:
            if self.cfg.overflow_policy == "drop_oldest":
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    self._queue.put_nowait(sample)
            self.stats.dropped_queue_full += 1
            if self.stats.dropped_queue_full % 100 == 1:
                log.error(
                    "pipeline queue full (%d): %d samples dropped so far - "
                    "sink is not keeping up",
                    self.cfg.queue_max,
                    self.stats.dropped_queue_full,
                )

    # --------------------------------------------------------------------- run #
    async def start(self) -> None:
        if self._consumer_task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._thread_id = threading.get_ident()
        self._consumer_task = asyncio.create_task(
            self._consume(), name="pipeline-consume"
        )

    async def wait(self) -> None:
        if self._consumer_task is not None:
            await self._consumer_task

    async def stop(self) -> None:
        """Drain what we can, then stop. Never loses a batch silently."""
        if self._closing:
            await self._flush(final=True)
            return

        self._closing = True
        await self._drain_queue()
        await self._flush(final=True)

        task = self._consumer_task
        if task is not None and not task.done():
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(self._stop_token)
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("pipeline consumer ended with an error")

        # A sample could have been appended between the first drain and the
        # consumer noticing the close. Flush once more so it is not stranded.
        await self._flush(final=True)

    async def _drain_queue(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if item is not self._stop_token:
                self._buffer.append(cast("Sample", item))

    # ---------------------------------------------------------------- batching #
    async def _consume(self) -> None:
        try:
            while not self._closing:
                timeout = max(
                    0.05,
                    self.cfg.flush_interval_s - (time.monotonic() - self._last_flush),
                )
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except TimeoutError:
                    await self._flush()
                    continue

                if item is self._stop_token:
                    return
                sample = cast("Sample", item)
                self._buffer.append(sample)
                source = sample.source.value
                self.stats.per_source[source] = self.stats.per_source.get(source, 0) + 1
                if len(self._buffer) >= self.cfg.max_samples:
                    await self._flush()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pipeline consumer failed")
            self.failed.set()
            raise

    async def _flush(self, *, final: bool = False) -> None:
        if not self._buffer:
            self._last_flush = time.monotonic()
            return

        by_device: dict[str, list[Sample]] = {}
        for sample in self._buffer:
            by_device.setdefault(sample.device_id, []).append(sample)
        self._buffer = []
        self._last_flush = time.monotonic()

        for device_id in sorted(by_device):
            self._seq += 1
            batch = Batch(
                gateway_id=self.gateway_id,
                device_id=device_id,
                seq=self._seq,
                samples=by_device[device_id],
            )
            self.stats.batches_built += 1
            await self._deliver(batch)

        if final:
            log.info("pipeline flushed %d device batch(es) on shutdown", len(by_device))

    async def _deliver(self, batch: Batch) -> None:
        try:
            await self.sink.send(batch)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.stats.send_failures += 1
            self.stats.dropped_unsendable += len(batch.samples)
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            log.error("batch #%d failed: %s", batch.seq, exc)
            return

        self.stats.batches_sent += 1
        self.stats.last_batch_at = time.time()

    # ------------------------------------------------------------------ health #
    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def buffer_depth(self) -> int:
        return len(self._buffer)

    def snapshot(self) -> dict[str, object]:
        return {
            "accepted": self.stats.accepted,
            "batches_built": self.stats.batches_built,
            "batches_sent": self.stats.batches_sent,
            "send_failures": self.stats.send_failures,
            "dropped_queue_full": self.stats.dropped_queue_full,
            "dropped_unsendable": self.stats.dropped_unsendable,
            "queue_depth": self.queue_depth,
            "buffer_depth": self.buffer_depth,
            "per_source": dict(self.stats.per_source),
            "last_error": self.stats.last_error,
            "last_batch_at": self.stats.last_batch_at,
        }
