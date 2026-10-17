"""Configuration loading.

The YAML file is the normal interface. Defaults live on the models, so a site
config only states what differs. An enabled source is mandatory: a collector
that silently ingests nothing would report healthy while doing no work.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from edge_collector.identifiers import DEVICE_ID_PATTERN, GATEWAY_ID_PATTERN

DEFAULT_CONFIG_PATH = Path("config/collector.yaml")


class ConfigError(RuntimeError):
    """Raised when configuration is missing, malformed, or inconsistent."""


class BatchingConfig(BaseModel):
    """The two flush triggers, and the bound on memory between them."""

    max_samples: int = Field(default=100, gt=0)
    flush_interval_s: float = Field(default=1.0, gt=0)
    queue_max: int = Field(
        default=10_000,
        gt=0,
        description="Bounded so a slow sink can never exhaust device memory",
    )
    overflow_policy: Literal["drop_oldest", "drop_newest"] = "drop_oldest"


class HealthConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8081, ge=0, le=65535)


class SyntheticMetricConfig(BaseModel):
    name: str = Field(min_length=1)
    value: float
    step: float = 0.0
    unit: str | None = None


class SyntheticSourceConfig(BaseModel):
    """Deterministic development source; the surrogate for the first smoke test."""

    kind: Literal["synthetic"] = "synthetic"
    enabled: bool = False
    device_id: str = Field(default="plc-line-1", pattern=DEVICE_ID_PATTERN)
    interval_s: float = Field(default=1.0, gt=0)
    metrics: list[SyntheticMetricConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _metrics_required_when_enabled(self) -> SyntheticSourceConfig:
        if self.enabled and not self.metrics:
            raise ValueError(
                "synthetic source is enabled but no metrics are configured"
            )
        return self


class SourcesConfig(BaseModel):
    synthetic: SyntheticSourceConfig = Field(default_factory=SyntheticSourceConfig)

    def enabled_sources(self) -> list[SyntheticSourceConfig]:
        return [source for source in (self.synthetic,) if source.enabled]


class CollectorConfig(BaseModel):
    gateway_id: str = Field(default="dev-gateway-01", pattern=GATEWAY_ID_PATTERN)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    batching: BatchingConfig = Field(default_factory=BatchingConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)

    @model_validator(mode="after")
    def _source_required(self) -> CollectorConfig:
        if not self.sources.enabled_sources():
            raise ValueError("at least one source must be enabled")
        return self


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def load_config(path: str | Path | None = None) -> CollectorConfig:
    """Load and validate the collector configuration."""
    candidate = path or os.environ.get("EDGE_COLLECTOR_CONFIG") or DEFAULT_CONFIG_PATH
    cfg_path = Path(candidate)
    if not cfg_path.exists():
        raise ConfigError(f"config file not found: {cfg_path}")

    data = _read_yaml(cfg_path)
    try:
        return CollectorConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration ({cfg_path}):\n{exc}") from exc
