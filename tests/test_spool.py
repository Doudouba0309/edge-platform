"""SQLite store-and-forward behaviour."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from edge_collector.config import SpoolConfig
from edge_collector.spool import Spool


def _spool(tmp_path: Path, **overrides: object) -> Spool:
    values: dict[str, object] = {
        "enabled": True,
        "path": str(tmp_path / "spool.sqlite3"),
        "max_bytes": 10_000,
        "replay_interval_s": 1.0,
    }
    values.update(overrides)
    spool = Spool(SpoolConfig(**values))  # type: ignore[arg-type]
    spool.open()
    return spool


def test_append_peek_delete_and_count(tmp_path: Path) -> None:
    spool = _spool(tmp_path)

    assert spool.append(b"first")
    assert spool.append(b"second")
    assert spool.count() == 2
    assert spool.bytes_buffered() == 11

    records = spool.peek()
    assert [record.payload for record in records] == [b"first", b"second"]

    spool.delete([records[0].id])
    assert spool.count() == 1
    assert [record.payload for record in spool.peek()] == [b"second"]

    spool.close()


def test_wal_mode_is_enabled(tmp_path: Path) -> None:
    spool = _spool(tmp_path)
    spool.append(b"payload")
    spool.close()

    conn = sqlite3.connect(tmp_path / "spool.sqlite3")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"


def test_spool_survives_reopen(tmp_path: Path) -> None:
    spool = _spool(tmp_path)
    spool.append(b"payload")
    spool.close()

    reopened = _spool(tmp_path)
    assert reopened.count() == 1
    assert reopened.peek()[0].payload == b"payload"
    reopened.close()


def test_budget_drops_oldest_payloads(tmp_path: Path) -> None:
    spool = _spool(tmp_path, max_bytes=100)

    assert spool.append(b"a" * 60)
    assert spool.append(b"b" * 60)

    # 120 payload bytes exceeds the 100-byte budget; the oldest batch goes.
    assert spool.count() == 1
    assert spool.bytes_buffered() == 60
    assert spool.peek()[0].payload == b"b" * 60

    spool.close()


def test_oversized_payload_is_not_reported_as_stored(tmp_path: Path) -> None:
    spool = _spool(tmp_path, max_bytes=50)

    assert spool.append(b"x" * 100) is False
    assert spool.count() == 0
    assert spool.bytes_buffered() == 0

    spool.close()


def test_append_before_open_returns_false(tmp_path: Path) -> None:
    spool = Spool(SpoolConfig(enabled=True, path=str(tmp_path / "spool.sqlite3")))
    assert spool.append(b"payload") is False
    assert spool.count() == 0


def test_disabled_spool_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "spool.sqlite3"
    spool = Spool(SpoolConfig(enabled=False, path=str(path)))
    spool.open()
    assert spool.append(b"payload") is False
    assert spool.count() == 0
    assert not path.exists()
    spool.close()


def test_delete_empty_list_is_a_noop(tmp_path: Path) -> None:
    spool = _spool(tmp_path)
    spool.delete([])
    assert spool.count() == 0
    spool.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    spool = _spool(tmp_path)
    spool.close()
    spool.close()
