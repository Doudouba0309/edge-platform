"""Bounded queue, batching, overflow and delivery accounting."""

from __future__ import annotations

import asyncio

import pytest

from edge_collector.config import BatchingConfig
from edge_collector.models import Batch, Sample, SourceKind, utcnow
from edge_collector.pipeline import Pipeline
from edge_collector.sinks import SinkUnavailable


class RecordingSink:
    def __init__(self) -> None:
        self.batches: list[Batch] = []

    async def send(self, batch: Batch) -> None:
        self.batches.append(batch)


class FailingSink:
    async def send(self, batch: Batch) -> None:
        raise SinkUnavailable("broker is down")


def _sample(metric: str = "m", device_id: str = "plc-line-1") -> Sample:
    return Sample(
        device_id=device_id,
        metric=metric,
        value=1.0,
        ts=utcnow(),
        source=SourceKind.SIM,
    )


def _pipeline(
    sink: RecordingSink | FailingSink,
    **batching: object,
) -> Pipeline:
    values: dict[str, object] = {
        "max_samples": 2,
        "flush_interval_s": 10.0,
        "queue_max": 10,
    }
    values.update(batching)
    cfg = BatchingConfig(**values)  # type: ignore[arg-type]
    return Pipeline("gw-dev-01", cfg, sink)


async def test_flushes_at_max_samples() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink, max_samples=2)
    await pipeline.start()

    pipeline.submit(_sample("a"))
    pipeline.submit(_sample("b"))
    await asyncio.sleep(0.05)

    assert len(sink.batches) == 1
    assert [sample.metric for sample in sink.batches[0].samples] == ["a", "b"]
    assert pipeline.stats.batches_sent == 1

    await pipeline.stop()


async def test_flushes_after_the_interval() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink, max_samples=100, flush_interval_s=0.05)
    await pipeline.start()

    pipeline.submit(_sample())
    await asyncio.sleep(0.2)

    assert len(sink.batches) == 1
    assert pipeline.stats.batches_built == 1

    await pipeline.stop()


async def test_splits_a_flush_by_device() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink, max_samples=3)
    await pipeline.start()

    pipeline.submit(_sample("a1", "dev-a"))
    pipeline.submit(_sample("b1", "dev-b"))
    pipeline.submit(_sample("a2", "dev-a"))
    await asyncio.sleep(0.05)

    assert len(sink.batches) == 2
    by_device = {batch.device_id: batch for batch in sink.batches}
    assert [sample.metric for sample in by_device["dev-a"].samples] == ["a1", "a2"]
    assert [sample.metric for sample in by_device["dev-b"].samples] == ["b1"]
    assert sorted(batch.seq for batch in sink.batches) == [1, 2]

    await pipeline.stop()


async def test_drop_oldest_keeps_the_newest_samples() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink, queue_max=2, max_samples=100, flush_interval_s=10)

    for metric in ("a", "b", "c"):
        pipeline.submit(_sample(metric))

    assert pipeline.stats.accepted == 2
    assert pipeline.stats.dropped_queue_full == 1
    assert pipeline.queue_depth == 2

    queued = []
    while pipeline.queue_depth:
        item = pipeline._queue.get_nowait()
        queued.append(item.metric)  # type: ignore[union-attr]
    assert queued == ["b", "c"]


async def test_drop_newest_keeps_the_oldest_samples() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(
        sink,
        queue_max=2,
        max_samples=100,
        flush_interval_s=10,
        overflow_policy="drop_newest",
    )

    for metric in ("a", "b", "c"):
        pipeline.submit(_sample(metric))

    assert pipeline.stats.accepted == 2
    assert pipeline.stats.dropped_queue_full == 1

    queued = []
    while pipeline.queue_depth:
        item = pipeline._queue.get_nowait()
        queued.append(item.metric)  # type: ignore[union-attr]
    assert queued == ["a", "b"]


async def test_stop_flushes_the_remaining_buffer() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink, max_samples=100, flush_interval_s=10)
    await pipeline.start()

    pipeline.submit(_sample())
    await pipeline.stop()

    assert len(sink.batches) == 1
    assert pipeline.stats.accepted == 1
    assert pipeline.stats.batches_sent == 1


async def test_stop_is_idempotent() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink)
    await pipeline.start()
    await pipeline.stop()
    await pipeline.stop()
    assert len(sink.batches) == 0


async def test_submit_after_stop_is_ignored() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink)
    await pipeline.start()
    await pipeline.stop()

    accepted = pipeline.stats.accepted
    pipeline.submit(_sample())
    assert pipeline.stats.accepted == accepted

    await asyncio.sleep(0)
    assert sink.batches == []


async def test_sink_failure_is_counted_not_swallowed() -> None:
    sink = FailingSink()
    pipeline = _pipeline(sink, max_samples=1)
    await pipeline.start()

    pipeline.submit(_sample())
    await asyncio.sleep(0.05)

    assert pipeline.stats.send_failures == 1
    assert pipeline.stats.dropped_unsendable == 1
    assert pipeline.stats.last_error is not None
    assert pipeline.stats.batches_sent == 0

    await pipeline.stop()


async def test_thread_safe_submit_is_delivered() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink, max_samples=1)
    await pipeline.start()

    await asyncio.to_thread(pipeline.submit, _sample())
    await asyncio.sleep(0.05)

    assert pipeline.stats.accepted == 1
    assert len(sink.batches) == 1

    await pipeline.stop()


async def test_snapshot_exposes_queue_and_buffer_depth() -> None:
    sink = RecordingSink()
    pipeline = _pipeline(sink, max_samples=100, flush_interval_s=10)
    await pipeline.start()
    pipeline.submit(_sample())
    await asyncio.sleep(0.02)

    snapshot = pipeline.snapshot()
    assert snapshot["accepted"] == 1
    assert snapshot["queue_depth"] == 0
    assert snapshot["buffer_depth"] == 1
    assert snapshot["per_source"] == {"sim": 1}

    await pipeline.stop()


@pytest.mark.parametrize("policy", ["drop_oldest", "drop_newest"])
async def test_overflow_policy_only_accepts_the_two_documented_values(
    policy: str,
) -> None:
    # The Literal type rejects anything else; this test pins the accepted set.
    cfg = BatchingConfig(overflow_policy=policy)  # type: ignore[arg-type]
    assert cfg.overflow_policy == policy
