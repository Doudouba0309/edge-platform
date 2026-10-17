"""SQLite store-and-forward spool.

An edge gateway loses its uplink: cellular drops, the plant firewall reboots,
someone unplugs the switch. Without buffering, every sample produced during that
window is gone. With it, the collector keeps ingesting and replays when the sink
comes back.

SQLite in WAL mode is deliberate: crash-safe, no extra service, and it survives
power loss. The budget applies to **payload bytes**, not file size — SQLite does
not return freed pages promptly, so a file-size budget would purge forever.

Threading: the pipeline calls these methods from worker threads
(``asyncio.to_thread``), so the connection is opened with
``check_same_thread=False`` and every operation is serialised behind an RLock.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from edge_collector.config import SpoolConfig

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS spool (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL    NOT NULL,
    payload    BLOB    NOT NULL
);
CREATE INDEX IF NOT EXISTS spool_created_at ON spool (created_at);
"""


@dataclass(frozen=True)
class SpoolRecord:
    id: int
    created_at: float
    payload: bytes


class Spool:
    """FIFO disk buffer. Methods are blocking and thread-safe."""

    def __init__(self, cfg: SpoolConfig) -> None:
        self.cfg = cfg
        self.path = Path(cfg.path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    def open(self) -> None:
        if not self.cfg.enabled:
            return
        with self._lock:
            if self._conn is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self.path,
                timeout=5.0,
                isolation_level=None,
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            # Must be set before the first table is created; lets us hand pages
            # back to the filesystem after old batches are deleted.
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.executescript(_SCHEMA)
            self._conn = conn
            pending = self._count_locked()
        log.info("spool ready at %s (%d pending)", self.path, pending)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------ write #
    def append(self, payload: bytes) -> bool:
        """Buffer one batch. Returns False if it could not be stored."""
        with self._lock:
            if self._conn is None:
                return False
            try:
                cursor = self._conn.execute(
                    "INSERT INTO spool (created_at, payload) VALUES (?, ?)",
                    (time.time(), payload),
                )
                row_id = cursor.lastrowid
            except sqlite3.Error as exc:
                log.error("spool append failed: %s", exc)
                return False
            self._enforce_limits_locked()
            if row_id is None:
                return False
            kept = self._conn.execute("SELECT 1 FROM spool WHERE id = ?", (row_id,)).fetchone()
            return kept is not None

    def _enforce_limits_locked(self) -> None:
        """Drop oldest rows until buffered payload bytes fit under the budget."""
        conn = self._conn
        if conn is None:
            return
        budget = int(self.cfg.max_bytes * 0.9)
        buffered = self._bytes_locked()
        if buffered <= self.cfg.max_bytes:
            return

        dropped = 0
        while buffered > budget:
            row = conn.execute(
                "SELECT id, LENGTH(payload) FROM spool ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                break
            conn.execute("DELETE FROM spool WHERE id = ?", (row[0],))
            buffered -= int(row[1])
            dropped += 1
            if dropped > 100_000:  # safety valve
                break
        if dropped:
            log.warning(
                "spool over budget (%d B configured): discarded %d oldest batches",
                self.cfg.max_bytes,
                dropped,
            )
            self._reclaim_space_locked()

    def _reclaim_space_locked(self) -> None:
        """Return freed pages to the filesystem once the file is well oversized."""
        conn = self._conn
        if conn is None:
            return
        try:
            if self._size_locked() > self.cfg.max_bytes * 2:
                conn.execute("PRAGMA incremental_vacuum")
                log.debug("spool reclaimed space; file now %d B", self._size_locked())
        except sqlite3.Error as exc:  # pragma: no cover - best effort
            log.debug("spool incremental_vacuum failed: %s", exc)

    # ------------------------------------------------------------------- read #
    def peek(self, limit: int = 100) -> list[SpoolRecord]:
        with self._lock:
            conn = self._conn
            if conn is None:
                return []
            rows = conn.execute(
                "SELECT id, created_at, payload FROM spool ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [SpoolRecord(id=row[0], created_at=row[1], payload=row[2]) for row in rows]

    def delete(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            conn = self._conn
            if conn is None:
                return
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM spool WHERE id IN ({placeholders})", ids)

    def count(self) -> int:
        with self._lock:
            return self._count_locked()

    def bytes_buffered(self) -> int:
        """Total payload bytes currently buffered — the value the budget applies to."""
        with self._lock:
            return self._bytes_locked()

    def size_bytes(self) -> int:
        """Approximate on-disk size from the page count."""
        with self._lock:
            return self._size_locked()

    # ------------------------------------------------------- lock-free helpers #
    def _count_locked(self) -> int:
        if self._conn is None:
            return 0
        row = self._conn.execute("SELECT COUNT(*) FROM spool").fetchone()
        return int(row[0]) if row else 0

    def _bytes_locked(self) -> int:
        if self._conn is None:
            return 0
        row = self._conn.execute("SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM spool").fetchone()
        return int(row[0]) if row else 0

    def _size_locked(self) -> int:
        if self._conn is None:
            return 0
        page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
        return int(page_count) * int(page_size)
