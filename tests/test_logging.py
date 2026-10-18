import json
import logging

from edge_collector.logging_setup import (
    ContextFilter,
    JsonFormatter,
    configure_logging,
    redact,
    reset_log_context,
    set_log_context,
)


def test_redact_hides_passwords_and_private_keys() -> None:
    fake_pem = "-----BEGIN " + "PRIVATE KEY-----\nZmFrZQ==\n-----END " + "PRIVATE KEY-----"
    text = f"password=hunter2 token: abc123\n{fake_pem}"
    cleaned = redact(text)
    assert "hunter2" not in cleaned
    assert "abc123" not in cleaned
    assert "ZmFrZQ" not in cleaned
    assert "[REDACTED]" in cleaned
    assert redact("Authorization: Bearer abc123") == "Authorization: [REDACTED]"
    assert redact("Proxy-Authorization: Basic dXNlcjpwYXNz") == "Proxy-Authorization: [REDACTED]"
    assert redact("api_key=abc123") == "api_key=[REDACTED]"


def test_json_formatter_includes_context_and_redacts() -> None:
    record = logging.LogRecord(
        name="edge.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="reading %s password=hunter2",
        args=("temperature",),
        exc_info=None,
    )
    token = set_log_context(gateway_id="gw-1", batch_seq=7, component_version="1.0.10")
    try:
        ContextFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_log_context(token)

    assert payload["gateway_id"] == "gw-1"
    assert payload["batch_seq"] == 7
    assert payload["component_version"] == "1.0.10"
    assert "hunter2" not in payload["message"]
    assert payload["level"] == "INFO"


def test_configure_logging_writes_a_rotating_json_file(tmp_path) -> None:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    log_path = tmp_path / "collector.log"
    try:
        configure_logging(
            level="INFO",
            json_logs=True,
            log_file=str(log_path),
            max_bytes=300,
            backup_count=2,
        )
        logger = logging.getLogger("edge.test.file")
        token = set_log_context(gateway_id="gw-file", batch_seq=1)
        try:
            for index in range(30):
                logger.info("batch %d for the file", index)
        finally:
            reset_log_context(token)
        for handler in root.handlers:
            handler.flush()

        files = sorted(tmp_path.glob("collector.log*"))
        assert files
        first = files[0].read_text(encoding="utf-8").splitlines()[0]
        payload = json.loads(first)
        assert payload["gateway_id"] == "gw-file"
        assert "message" in payload
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        for handler in old_handlers:
            root.addHandler(handler)
        root.setLevel(old_level)
