"""Configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from edge_collector.config import CollectorConfig, ConfigError, load_config


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_the_default_development_config() -> None:
    cfg = load_config("config/collector.yaml")
    assert cfg.gateway_id == "dev-gateway-01"
    assert cfg.batching.max_samples == 10
    assert cfg.health.port == 8081
    assert cfg.sink.kind == "log"
    assert cfg.spool.enabled is False
    assert cfg.sources.synthetic.enabled
    assert [metric.name for metric in cfg.sources.synthetic.metrics] == [
        "temperature",
        "pressure",
    ]


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_invalid_yaml_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.yaml", "gateway_id: [unclosed\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_top_level_must_be_a_mapping(tmp_path: Path) -> None:
    path = _write(tmp_path, "list.yaml", "- gateway_id\n- other\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(path)


def test_invalid_gateway_id_is_an_error(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bad-id.yaml",
        """
gateway_id: gw/1
sources:
  synthetic:
    enabled: true
    metrics:
      - {name: temperature, value: 25.0}
""",
    )
    with pytest.raises(ConfigError, match="invalid configuration"):
        load_config(path)


def test_at_least_one_source_must_be_enabled(tmp_path: Path) -> None:
    path = _write(tmp_path, "idle.yaml", "gateway_id: gw-dev-01\n")
    with pytest.raises(ConfigError, match="at least one source"):
        load_config(path)


def test_enabled_synthetic_source_requires_metrics(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "empty-source.yaml",
        """
gateway_id: gw-dev-01
sources:
  synthetic:
    enabled: true
    metrics: []
""",
    )
    with pytest.raises(ConfigError, match="no metrics"):
        load_config(path)


def test_env_var_selects_the_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "env.yaml",
        """
gateway_id: gw-env-01
sources:
  synthetic:
    enabled: true
    metrics:
      - {name: temperature, value: 25.0}
""",
    )
    monkeypatch.setenv("EDGE_COLLECTOR_CONFIG", str(path))
    assert load_config().gateway_id == "gw-env-01"


def test_collector_config_rejects_an_empty_source_set() -> None:
    with pytest.raises(ValueError, match="at least one source"):
        CollectorConfig()


def test_loads_the_smoke_config() -> None:
    cfg = load_config("config/collector-smoke.yaml")
    assert cfg.sink.kind == "mqtt"
    assert cfg.sink.port == 8883
    assert cfg.spool.enabled is True
    assert cfg.spool.path == "var/spool.sqlite3"
    assert cfg.sources.synthetic.interval_s == 0.2


def test_partial_mqtt_tls_config_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bad-tls.yaml",
        """
gateway_id: gw-dev-01
sink:
  kind: mqtt
  ca_file: certs/ca.crt
sources:
  synthetic:
    enabled: true
    metrics:
      - {name: temperature, value: 25.0}
""",
    )
    with pytest.raises(ConfigError, match="ca_file, cert_file and key_file"):
        load_config(path)
