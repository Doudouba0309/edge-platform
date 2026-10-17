"""Structured, bounded and redacted logging.

The collector runs unattended on a device that may be in another country. Logs
are evidence, not decoration, so they are JSON by default, written to a rotating
file as well as stdout, and scrubbed of obvious secret material.

The context helpers let one batch read/publish cycle carry the same gateway,
device and sequence fields through every log line without threading arguments
through every function.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "edge_log_context", default=None
)

_CONTEXT_FIELDS = (
    "gateway_id",
    "device_id",
    "batch_seq",
    "event",
    "error_code",
    "service_version",
)

_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_SECRET_RE = re.compile(
    r"(?i)((?:password|passwd|secret|token|private[_-]?key|access[_-]?key|"
    r"authorization)\s*[=:]\s*)([^\s,;]+)"
)


def redact(text: str) -> str:
    """Remove obvious secrets from a log line or support bundle."""
    text = _PEM_RE.sub("[REDACTED PRIVATE KEY]", text)
    return _SECRET_RE.sub(r"\1[REDACTED]", text)


def set_log_context(**kwargs: Any) -> contextvars.Token[dict[str, Any] | None]:
    """Add fields to log records for the current async/task context."""
    return _CONTEXT.set({**(_CONTEXT.get() or {}), **kwargs})


def reset_log_context(token: contextvars.Token[dict[str, Any] | None]) -> None:
    _CONTEXT.reset(token)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (_CONTEXT.get() or {}).items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in _CONTEXT_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, separators=(",", ":"), default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(
    *,
    level: str = "INFO",
    json_logs: bool = True,
    log_file: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure the process root logger once.

    A failure to open the file must not prevent the collector from starting; the
    stream handler remains available and the failure is reported.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(level)
    formatter: logging.Formatter = JsonFormatter() if json_logs else TextFormatter()
    context_filter = ContextFilter()

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    stream.addFilter(context_filter)
    root.addHandler(stream)

    if log_file:
        path = Path(log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        except OSError as exc:
            root.warning("could not open log file %s: %s", log_file, exc)
        else:
            file_handler.setFormatter(formatter)
            file_handler.addFilter(context_filter)
            root.addHandler(file_handler)
