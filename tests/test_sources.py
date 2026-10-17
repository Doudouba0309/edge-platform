"""Synthetic source behaviour."""

from __future__ import annotations

import asyncio

import pytest

from edge_collector.config import SyntheticMetricConfig, SyntheticSourceConfig
from edge_collector.models import Quality, Sample, SourceKind
from edge_collector.sources.synthetic import SyntheticSource


def _source(
    *,
    interval_s: float = 10.0,
    metrics: list[SyntheticMetricConfig] | None = None,
) -> tuple[SyntheticSource, list[Sample]]:
    emitted: list[Sample] = []
    cfg = SyntheticSourceConfig(
        enabled=True,
        device_id="plc-line-1",
        interval_s=interval_s,
        metrics=metrics
        or [
            SyntheticMetricConfig(name="temperature", value=25.0, step=0.5, unit="degC"),
            SyntheticMetricConfig(name="pressure", value=101.3, unit="kPa"),
        ],
    )
    return SyntheticSource(cfg, emitted.append), emitted


def test_emit_once_is_deterministic() -> None:
    source, emitted = _source()
    first = source.emit_once()
    second = source.emit_once()

    assert [sample.value for sample in first] == [25.5, 101.3]
    assert [sample.value for sample in second] == [26.0, 101.3]
    assert emitted == first + second


def test_emitted_samples_have_the_canonical_shape() -> None:
    source, _ = _source()
    sample = source.emit_once()[0]

    assert sample.device_id == "plc-line-1"
    assert sample.metric == "temperature"
    assert sample.source is SourceKind.SIM
    assert sample.quality is Quality.GOOD
    assert sample.unit == "degC"
    assert sample.origin == "synthetic:temperature"
    assert sample.ts.tzinfo is not None


async def test_start_sets_connected_and_stop_clears_it() -> None:
    source, _ = _source()

    await source.start()
    assert source.healthy
    assert source.stats.connected
    await source.start()  # idempotent
    await source.stop()
    assert not source.healthy
    await source.stop()  # idempotent
    assert not source.healthy


async def test_source_emits_on_its_interval() -> None:
    source, emitted = _source(interval_s=0.01)

    await source.start()
    await asyncio.sleep(0.1)
    await source.stop()
    assert emitted, "the source should have emitted at least once"
    assert source.stats.received == len(emitted)


async def test_stop_before_start_is_safe() -> None:
    source, emitted = _source()

    await source.stop()
    assert not source.healthy
    assert emitted == []


@pytest.mark.parametrize("step", [0.0, 0.5, -1.0])
def test_value_follows_value_plus_step_times_tick(step: float) -> None:
    metrics = [SyntheticMetricConfig(name="m", value=10.0, step=step)]
    source, _ = _source(metrics=metrics)
    assert source.emit_once()[0].value == 10.0 + step
    assert source.emit_once()[0].value == 10.0 + step * 2


def test_emit_fn_is_called_once_per_sample() -> None:
    emitted: list[Sample] = []
    cfg = SyntheticSourceConfig(
        enabled=True,
        metrics=[SyntheticMetricConfig(name="m", value=1.0)],
    )
    source = SyntheticSource(cfg, emitted.append)
    source.emit_once()
    source.emit_once()
    assert len(emitted) == 2


def test_source_has_a_stable_name() -> None:
    source, _ = _source()
    assert source.name == "synthetic"
    assert source.kind is SourceKind.SIM
