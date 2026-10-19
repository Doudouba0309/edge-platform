"""Phase 1A point-map contract, validation and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from edge_collector.__main__ import main
from edge_collector.pointmap import (
    PointMap,
    PointMapError,
    dumps_point_map_schema,
    load_point_map,
)

ROOT = Path(__file__).resolve().parents[1]
SOLAR_MAP = ROOT / "config" / "pointmaps" / "solar-surrogate.yaml"


def _map(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "version": 1,
        "source": {
            "id": "inv-yard-1",
            "type": "modbus_tcp",
            "host": "127.0.0.1",
            "port": 5020,
            "slaves": [
                {
                    "unit_id": 1,
                    "device_id": "inv-01",
                    "points": [
                        {
                            "metric": "ac_power_kw",
                            "function": "holding_register",
                            "address": 100,
                            "type": "float32",
                            "unit": "kW",
                        }
                    ],
                }
            ],
        },
    }
    data.update(overrides)
    return data


def test_solar_surrogate_map_loads() -> None:
    point_map = load_point_map(SOLAR_MAP)
    assert point_map.source.id == "inv-yard-1"
    assert len(point_map.source.slaves) == 3
    assert point_map.point_count == 12


def test_committed_point_map_schema_matches_models() -> None:
    committed = (ROOT / "schemas" / "point-map.schema.json").read_text()
    assert committed == dumps_point_map_schema()


def test_same_metric_on_different_devices_is_allowed() -> None:
    data = _map()
    source = data["source"]  # type: ignore[index]
    source["slaves"].append(  # type: ignore[index]
        {
            "unit_id": 2,
            "device_id": "inv-02",
            "points": [
                {
                    "metric": "ac_power_kw",
                    "function": "holding_register",
                    "address": 100,
                    "type": "float32",
                }
            ],
        }
    )
    point_map = PointMap.model_validate(data)
    assert point_map.point_count == 2


def test_duplicate_metric_on_same_device_is_rejected() -> None:
    data = _map()
    source = data["source"]  # type: ignore[index]
    source["slaves"].append(  # type: ignore[index]
        {
            "unit_id": 2,
            "device_id": "inv-01",
            "points": [
                {
                    "metric": "ac_power_kw",
                    "function": "holding_register",
                    "address": 200,
                    "type": "float32",
                }
            ],
        }
    )
    with pytest.raises(ValidationError, match="duplicate metric"):
        PointMap.model_validate(data)


def test_duplicate_unit_id_is_rejected() -> None:
    data = _map()
    source = data["source"]  # type: ignore[index]
    source["slaves"].append(  # type: ignore[index]
        {
            "unit_id": 1,
            "device_id": "inv-02",
            "points": [
                {
                    "metric": "ac_power_kw",
                    "function": "holding_register",
                    "address": 200,
                    "type": "float32",
                }
            ],
        }
    )
    with pytest.raises(ValidationError, match="duplicate unit_id"):
        PointMap.model_validate(data)


def test_unknown_fields_are_rejected() -> None:
    data = _map(extra="nope")
    with pytest.raises(ValidationError):
        PointMap.model_validate(data)


def test_coil_requires_bool_and_register_rejects_bool() -> None:
    data = _map()
    point = data["source"]["slaves"][0]["points"][0]  # type: ignore[index]
    point["function"] = "coil"
    point["type"] = "int16"
    with pytest.raises(ValidationError, match="requires type 'bool'"):
        PointMap.model_validate(data)

    data = _map()
    point = data["source"]["slaves"][0]["points"][0]  # type: ignore[index]
    point["type"] = "bool"
    with pytest.raises(ValidationError, match="cannot use type 'bool'"):
        PointMap.model_validate(data)


def test_string_requires_length_and_length_is_string_only() -> None:
    data = _map()
    point = data["source"]["slaves"][0]["points"][0]  # type: ignore[index]
    point["type"] = "string"
    with pytest.raises(ValidationError, match="require length"):
        PointMap.model_validate(data)

    data = _map()
    point = data["source"]["slaves"][0]["points"][0]  # type: ignore[index]
    point["length"] = 4
    with pytest.raises(ValidationError, match="only valid for string"):
        PointMap.model_validate(data)


def test_bad_metric_and_address_are_rejected() -> None:
    data = _map()
    point = data["source"]["slaves"][0]["points"][0]  # type: ignore[index]
    point["metric"] = "AC Power"
    with pytest.raises(ValidationError):
        PointMap.model_validate(data)

    data = _map()
    point = data["source"]["slaves"][0]["points"][0]  # type: ignore[index]
    point["address"] = -1
    with pytest.raises(ValidationError):
        PointMap.model_validate(data)


def test_load_point_map_reports_yaml_errors(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("version: [\n")
    with pytest.raises(PointMapError, match="invalid YAML"):
        load_point_map(path)


def test_validate_point_map_cli_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate-point-map", str(SOLAR_MAP)]) == 0
    assert "3 slave(s), 12 point(s)" in capsys.readouterr().out


def test_validate_point_map_cli_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _map(extra="nope")
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data))
    assert main(["validate-point-map", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "INVALID:" in captured.err


def test_schema_is_valid_json() -> None:
    schema = json.loads((ROOT / "schemas" / "point-map.schema.json").read_text())
    assert schema["$id"].endswith("point-map.schema.json")
    assert schema["properties"]["version"]["const"] == 1
