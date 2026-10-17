"""The ingest -> batch -> deliver pipeline.

Three decisions dominate this file:

* **One bounded queue.** Memory can never grow without limit on a gateway with
  1 GB of RAM. When the queue fills we drop, loudly, using a configurable
  policy.
* **Two flush triggers.** A batch goes out when it reaches ``max_samples`` *or*
  when ``flush_interval_s`` has elapsed, whichever comes first.
* **Store-and-forward owns ordering.** Once the spool has anything, new batches
  are appended behind it; the replay loop sends oldest-first. Nothing overtakes
  the backlog.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import cast

from pydantic import ValidationError

from edge_collector.config import BatchingConfig
from edge_collector.models import Batch, Sample
from edge_collector.sinks import Sink, SinkUnavailable
from edge_collector.spool import Spool

log = logging.getLogger(__name__)

REPLAY_BATCH_SIZE = 100


@dataclass
class PipelineStats:
    accepted: int = 0
    dropped_queue_full: int = 0
    dropped_unsendable: int = 0
    send_failures: int = 0
    batches_built: int = 0
    batches_sent: int = 0
    spooled: int = 0
    replayed: int = 0
    spool_corrupt_dropped: int = 0
    spool_pending: int = 0
    last_error: str | None = None
    last_batch_at: float | None = None
    per_source: dict[str, int] = field(default_factory=dict)


class Pipeline:
    def __init__(
        self,
        gateway_id: str,
        cfg: BatchingConfig,
        sink: Sink,
        spool: Spool,
    ) -> None:
        self.gateway_id = gateway_id
        self.sink = sink
        self.spool = spool
        self.cfg = cfg
        self.stats = PipelineStats()
        self.failed = asyncio.Event()

        self._queue: asyncio.Queue[Sample | object] = asyncio.Queue(maxsize=cfg.queue_max)
        self._stop_token = object()
        self._buffer: list[Sample] = []
        self._seq = 0
        self._closing = False
        self._closing_event = asyncio.Event()
        self._consumer_task: asyncio.Task[None] | None = None
        self._replay_task: asyncio.Task[None] | None = None
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
                    "pipeline queue full (%d): %d samples dropped so far - sink is not keeping up",
                    self.cfg.queue_max,
                    self.stats.dropped_queue_full,
                )

    # --------------------------------------------------------------------- run #
    async def start(self) -> None:
        if self._consumer_task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._thread_id = threading.get_ident()
        self._consumer_task = asyncio.create_task(self._consume(), name="pipeline-consume")
        if self.spool.enabled:
            self.stats.spool_pending = await asyncio.to_thread(self.spool.count)
            self._replay_task = asyncio.create_task(self._replay_loop(), name="pipeline-replay")

    async def wait(self) -> None:
        if self._consumer_task is not None:
            await self._consumer_task

    async def stop(self) -> None:
        """Drain what we can, then stop. Never loses a batch silently."""
        if self._closing:
            await self._flush(final=True)
            return

        self._closing = True
        self._closing_event.set()

        replay_task = self._replay_task
        if replay_task is not None:
            replay_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await replay_task

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
        payload = batch.to_json()

        if self.spool.enabled:
            pending = await asyncio.to_thread(self.spool.count)
            self.stats.spool_pending = pending
            if pending == 0:
                try:
                    await self.sink.send(batch)
                    self._record_sent()
                    return
                except SinkUnavailable as exc:
                    self.stats.send_failures += 1
                    self.stats.last_error = str(exc)
                    log.warning("sink unavailable, buffering batch #%d: %s", batch.seq, exc)

            stored = await asyncio.to_thread(self.spool.append, payload)
            if stored:
                self.stats.spooled += 1
                self.stats.spool_pending = await asyncio.to_thread(self.spool.count)
                log.info("spooled batch #%d behind %d pending", batch.seq, pending)
            else:
                self.stats.dropped_unsendable += len(batch.samples)
                log.error(
                    "could not spool batch #%d and sink is down - batch lost",
                    batch.seq,
                )
            return

        try:
            await self.sink.send(batch)
        except SinkUnavailable as exc:
            self.stats.send_failures += 1
            self.stats.dropped_unsendable += len(batch.samples)
            self.stats.last_error = str(exc)
            log.error("batch #%d dropped (no spool): %s", batch.seq, exc)
            return

        self._record_sent()

    def _record_sent(self) -> None:
        self.stats.batches_sent += 1
        self.stats.last_batch_at = time.time()

    # ------------------------------------------------------------------ replay #
    async def _replay_loop(self) -> None:
        interval = self.spool.cfg.replay_interval_s
        while not self._closing:
            try:
                await asyncio.wait_for(self._closing_event.wait(), timeout=interval)
                return
            except TimeoutError:
                pass

            try:
                await self._drain_spool()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.stats.last_error = f"spool replay failed: {exc}"
                log.exception("spool replay failed")

    async def _drain_spool(self) -> None:
        if not self.spool.enabled:
            return

        records = await asyncio.to_thread(self.spool.peek, REPLAY_BATCH_SIZE)
        if not records:
            self.stats.spool_pending = await asyncio.to_thread(self.spool.count)
            return

        done: list[int] = []
        for record in records:
            try:
                batch = Batch.from_json(record.payload)
            except ValidationError:
                self.stats.spool_corrupt_dropped += 1
                done.append(record.id)
                log.error("dropping corrupt spooled batch id=%d", record.id)
                continue

            try:
                await self.sink.send(batch)
            except SinkUnavailable:
                await asyncio.to_thread(self.spool.delete, done)
                self.stats.spool_pending = await asyncio.to_thread(self.spool.count)
                return

            done.append(record.id)
            self._record_sent()
            self.stats.replayed += 1

        await asyncio.to_thread(self.spool.delete, done)
        self.stats.spool_pending = await asyncio.to_thread(self.spool.count)
        if done:
            log.info("replayed %d buffered batch(es)", len(done))

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
            "spooled": self.stats.spooled,
            "replayed": self.stats.replayed,
            "spool_corrupt_dropped": self.stats.spool_corrupt_dropped,
            "spool_pending": self.stats.spool_pending,
            "spool_enabled": self.spool.enabled,
            "queue_depth": self.queue_depth,
            "buffer_depth": self.buffer_depth,
            "per_source": dict(self.stats.per_source),
            "last_error": self.stats.last_error,
            "last_batch_at": self.stats.last_batch_at,
        }
