"""Process wiring: config -> source -> pipeline -> sink, plus health and signals."""

from __future__ import annotations

import asyncio
import contextlib
import signal

from edge_collector.config import CollectorConfig, ConfigError
from edge_collector.health import HealthServer
from edge_collector.pipeline import Pipeline
from edge_collector.sinks import LogSink
from edge_collector.sources import EmitFn
from edge_collector.sources.base import Source
from edge_collector.sources.synthetic import SyntheticSource


def build_source(cfg: CollectorConfig, emit: EmitFn) -> Source:
    if cfg.sources.synthetic.enabled:
        return SyntheticSource(cfg.sources.synthetic, emit)
    raise ConfigError("no source is enabled")


class CollectorApp:
    def __init__(self, cfg: CollectorConfig) -> None:
        self.cfg = cfg
        self.pipeline = Pipeline(cfg.gateway_id, cfg.batching, LogSink())
        self.sources: list[Source] = [build_source(cfg, self.pipeline.submit)]
        self.health = HealthServer(cfg.health, self._snapshot)
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def _snapshot(self) -> dict[str, object]:
        state = self.pipeline.snapshot()
        sources: dict[str, object] = {}
        for source in self.sources:
            stats = source.stats
            sources[source.name] = {
                "connected": stats.connected,
                "received": stats.received,
                "dropped": stats.dropped,
                "filtered": stats.filtered,
                "parse_errors": stats.parse_errors,
                "reconnects": stats.reconnects,
                "last_sample_at": stats.last_sample_at,
            }
        state["sources"] = sources
        state["ready"] = all(source.healthy for source in self.sources)
        return state

    async def run(self, *, handle_signals: bool = True) -> None:
        loop = asyncio.get_running_loop()
        signals = (signal.SIGINT, signal.SIGTERM)

        if handle_signals:
            for sig in signals:
                with contextlib.suppress(NotImplementedError, RuntimeError):
                    loop.add_signal_handler(sig, self.request_stop)

        await self.pipeline.start()
        stop_task: asyncio.Task[bool] | None = None
        fail_task: asyncio.Task[bool] | None = None
        pipeline_failed = False

        try:
            for source in self.sources:
                await source.start()
            await self.health.start()

            stop_task = asyncio.create_task(self._stop.wait(), name="stop-signal")
            fail_task = asyncio.create_task(
                self.pipeline.failed.wait(), name="pipeline-failed"
            )
            done, _ = await asyncio.wait(
                {stop_task, fail_task}, return_when=asyncio.FIRST_COMPLETED
            )
            pipeline_failed = fail_task in done
        finally:
            if stop_task is not None:
                stop_task.cancel()
            if fail_task is not None:
                fail_task.cancel()

            for source in self.sources:
                await source.stop()
            await self.pipeline.stop()
            await self.health.stop()

            if handle_signals:
                for sig in signals:
                    with contextlib.suppress(NotImplementedError, RuntimeError):
                        loop.remove_signal_handler(sig)

        if pipeline_failed:
            raise RuntimeError("pipeline consumer failed; see logs")
