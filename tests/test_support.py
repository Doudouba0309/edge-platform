import json
import zipfile

from edge_collector.support import build_support_bundle


def test_support_bundle_contains_redacted_evidence(tmp_path) -> None:
    config = tmp_path / "collector.yaml"
    config.write_text(
        "gateway_id: gw-support\n"
        "log_level: INFO\n"
        "log_json: true\n"
        "log_file: var/collector.log\n"
        "spool:\n"
        "  enabled: false\n"
        "sink:\n"
        "  kind: log\n"
        "sources:\n"
        "  synthetic:\n"
        "    enabled: true\n"
        "    metrics:\n"
        "      - name: temperature\n"
        "        value: 21.5\n",
        encoding="utf-8",
    )
    log = tmp_path / "collector.log"
    fake_pem = "-----BEGIN " + "PRIVATE KEY-----\nZmFrZQ==\n-----END " + "PRIVATE KEY-----\n"
    log.write_text('{"message":"password=hunter2"}\n' + fake_pem, encoding="utf-8")
    output = tmp_path / "support.zip"

    path = build_support_bundle(
        config_path=config,
        output_path=output,
        log_files=[log],
        component_version="1.0.10",
    )

    assert path == output
    with zipfile.ZipFile(path) as bundle:
        names = bundle.namelist()
        assert "manifest.json" in names
        assert "config.yaml" in names
        assert "system.json" in names
        assert "logs/collector.log" in names
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["config_path"] == str(config)
        assert manifest["component_version"] == "1.0.10"
        assert "hunter2" not in bundle.read("logs/collector.log").decode()
        assert "ZmFrZQ" not in bundle.read("logs/collector.log").decode()
        assert "[REDACTED]" in bundle.read("logs/collector.log").decode()
