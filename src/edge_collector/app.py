"""Process wiring: config -> source -> pipeline -> sink, plus health and signals."""

from __future__ import annotations

import asyncio
import contextlib
import signal

from edge_collector.config import (
    CollectorConfig,
    ConfigError,
    GreengrassSinkConfig,
    LogSinkConfig,
    MqttSinkConfig,
)
from edge_collector.health import HealthServer
from edge_collector.logging_setup import reset_log_context, set_log_context
from edge_collector.pipeline import Pipeline
from edge_collector.sinks import GreengrassIpcSink, LogSink, MqttSink, Sink
from edge_collector.sources import EmitFn
from edge_collector.sources.base import Source
from edge_collector.sources.synthetic import SyntheticSource
from edge_collector.spool import Spool
from edge_collector.status import StatusReporter, collector_version


def build_source(cfg: CollectorConfig, emit: EmitFn) -> Source:
    if cfg.sources.synthetic.enabled:
        return SyntheticSource(cfg.sources.synthetic, emit)
    raise ConfigError("no source is enabled")


def build_sink(cfg: CollectorConfig) -> Sink:
    if isinstance(cfg.sink, MqttSinkConfig):
        return MqttSink(cfg.sink, gateway_id=cfg.gateway_id)
    if isinstance(cfg.sink, GreengrassSinkConfig):
        return GreengrassIpcSink(cfg.sink, gateway_id=cfg.gateway_id)
    if isinstance(cfg.sink, LogSinkConfig):
        return LogSink()
    raise ConfigError(f"unsupported sink kind: {cfg.sink.kind}")


class CollectorApp:
    def __init__(self, cfg: CollectorConfig) -> None:
        self.cfg = cfg
        self.sink = build_sink(cfg)
        self.spool = Spool(cfg.spool)
        self.pipeline = Pipeline(cfg.gateway_id, cfg.batching, self.sink, self.spool)
        self.sources: list[Source] = [build_source(cfg, self.pipeline.submit)]
        self.health = HealthServer(cfg.health, self._snapshot)
        self.status = StatusReporter(
            gateway_id=cfg.gateway_id,
            sink=self.sink,
            snapshot=self._snapshot,
            interval_s=cfg.status_interval_s,
            enabled=cfg.status_enabled,
        )
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
        sink_stats = self.sink.stats
        state["sources"] = sources
        state["sink"] = {
            "name": self.sink.name,
            "healthy": self.sink.healthy,
            "sent": sink_stats.sent,
            "failed": sink_stats.failed,
            "bytes_sent": sink_stats.bytes_sent,
            "last_error": sink_stats.last_error,
        }
        state["spool"] = {
            "enabled": self.spool.enabled,
            "path": str(self.spool.path),
            "pending": self.pipeline.stats.spool_pending,
        }
        state["ready"] = all(source.healthy for source in self.sources)
        return state

    async def run(self, *, handle_signals: bool = True) -> None:
        loop = asyncio.get_running_loop()
        signals = (signal.SIGINT, signal.SIGTERM)
        log_token = set_log_context(
            gateway_id=self.cfg.gateway_id,
            service_version=collector_version(),
        )

        if handle_signals:
            for sig in signals:
                with contextlib.suppress(NotImplementedError, RuntimeError):
                    loop.add_signal_handler(sig, self.request_stop)

        stop_task: asyncio.Task[bool] | None = None
        fail_task: asyncio.Task[bool] | None = None
        pipeline_failed = False

        try:
            self.spool.open()
            await self.sink.start()
            await self.pipeline.start()

            for source in self.sources:
                await source.start()
            await self.health.start()
            await self.status.start()

            stop_task = asyncio.create_task(self._stop.wait(), name="stop-signal")
            fail_task = asyncio.create_task(self.pipeline.failed.wait(), name="pipeline-failed")
            done, _ = await asyncio.wait(
                {stop_task, fail_task}, return_when=asyncio.FIRST_COMPLETED
            )
            pipeline_failed = fail_task in done
        finally:
            if stop_task is not None:
                stop_task.cancel()
            if fail_task is not None:
                fail_task.cancel()

            await self.status.stop()
            for source in self.sources:
                await source.stop()
            await self.pipeline.stop()
            await self.sink.stop()
            self.spool.close()
            await self.health.stop()

            if handle_signals:
                for sig in signals:
                    with contextlib.suppress(NotImplementedError, RuntimeError):
                        loop.remove_signal_handler(sig)
            reset_log_context(log_token)

        if pipeline_failed:
            raise RuntimeError("pipeline consumer failed; see logs")
