"""Health endpoint.

Deliberately dependency-free (asyncio + stdlib HTTP): no web framework to keep
patched on a device that may not be touched for years.

    GET /healthz   liveness,  always 200 while the process runs
    GET /readyz    200 when every enabled source is connected, else 503
    GET /stats     JSON counters
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

from edge_collector.config import HealthConfig

log = logging.getLogger(__name__)

SnapshotFn = Callable[[], dict[str, object]]

REASON_PHRASES = {
    200: "OK",
    404: "Not Found",
    503: "Service Unavailable",
}


class HealthServer:
    def __init__(self, cfg: HealthConfig, snapshot: SnapshotFn) -> None:
        self.cfg = cfg
        self._snapshot = snapshot
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int | None:
        if self._server is None or not self._server.sockets:
            return None
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            return
        if not self.cfg.enabled:
            log.info("health endpoint disabled")
            return
        self._server = await asyncio.start_server(
            self._handle, host=self.cfg.host, port=self.cfg.port
        )
        log.info(
            "health endpoint listening on http://%s:%d/healthz",
            self.cfg.host,
            self.port,
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            parts = request_line.decode("latin-1").split()
            path = parts[1].split("?", 1)[0] if len(parts) >= 2 else "/"
            # Drain headers so keep-alive clients do not stall us.
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line in (b"\r\n", b"\n", b""):
                    break

            state = self._snapshot()
            ready = bool(state.get("ready"))

            if path in ("/healthz", "/"):
                await self._respond(writer, 200, b"ok\n", "text/plain")
            elif path == "/readyz":
                body = b"ready\n" if ready else b"not ready\n"
                await self._respond(writer, 200 if ready else 503, body, "text/plain")
            elif path == "/stats":
                body = json.dumps(state, indent=2, default=str).encode()
                await self._respond(writer, 200, body, "application/json")
            else:
                await self._respond(writer, 404, b"not found\n", "text/plain")
        except (TimeoutError, ConnectionError):
            pass
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("health request failed: %s", exc)
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError, RuntimeError):
                await writer.wait_closed()

    @staticmethod
    async def _respond(
        writer: asyncio.StreamWriter,
        status: int,
        body: bytes,
        content_type: str,
    ) -> None:
        head = (
            f"HTTP/1.1 {status} {REASON_PHRASES.get(status, 'OK')}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        writer.write(head + body)
        await writer.drain()
