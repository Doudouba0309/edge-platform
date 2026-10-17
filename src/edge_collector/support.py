"""Redacted support bundle for remote diagnosis.

The bundle is deliberately simple: a ZIP of text/JSON evidence. It must be safe
to send to a support engineer and useful without a live shell on the gateway.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from edge_collector.logging_setup import redact

_MAX_LOG_BYTES = 1_000_000


def _version() -> str:
    try:
        return version("edge-collector")
    except PackageNotFoundError:
        return "unknown"


def _tail_text(path: Path, max_bytes: int = _MAX_LOG_BYTES) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        data = handle.read()
    return data.decode("utf-8", errors="replace")


def _spool_summary(config_path: Path) -> dict[str, Any]:
    import yaml

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        spool = config.get("spool", {})
        if not spool.get("enabled"):
            return {"enabled": False}
        path = Path(str(spool.get("path", "var/spool.sqlite3")))
        if not path.exists():
            return {"enabled": True, "path": str(path), "exists": False}
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            count = conn.execute("SELECT COUNT(*) FROM spool").fetchone()[0]
            payload_bytes = conn.execute(
                "SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM spool"
            ).fetchone()[0]
        finally:
            conn.close()
        return {
            "enabled": True,
            "path": str(path),
            "exists": True,
            "pending": int(count),
            "payload_bytes": int(payload_bytes),
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def build_support_bundle(
    *,
    config_path: Path,
    output_path: Path,
    log_files: list[Path] | None = None,
    stats_url: str | None = None,
    component_version: str = "unknown",
) -> Path:
    """Write a redacted ZIP and return its path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC).isoformat()
    manifest = {
        "created_at": created,
        "collector_version": _version(),
        "component_version": component_version,
        "host": platform.node(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "config_path": str(config_path),
    }

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")

        config_text = redact(config_path.read_text(encoding="utf-8"))
        bundle.writestr("config.yaml", config_text)

        system = {
            "uname": list(platform.uname()),
            "disk": {},
            "spool": _spool_summary(config_path),
        }
        try:
            usage = shutil.disk_usage(config_path.parent)
            system["disk"] = {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
            }
        except OSError as exc:
            system["disk"] = {"error": str(exc)}
        bundle.writestr("system.json", json.dumps(system, indent=2, default=str) + "\n")

        for log_path in log_files or []:
            if log_path.exists() and log_path.is_file():
                name = f"logs/{log_path.name}"
                bundle.writestr(name, redact(_tail_text(log_path)))

        if stats_url:
            try:
                with urllib.request.urlopen(stats_url, timeout=5) as response:
                    stats_text = response.read().decode("utf-8", errors="replace")
                bundle.writestr("stats.json", redact(stats_text))
            except Exception as exc:
                bundle.writestr("stats.error.txt", f"{type(exc).__name__}: {exc}\n")

    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="edge-collector-support",
        description="Collect a redacted support bundle for remote diagnosis.",
    )
    parser.add_argument("--config", type=Path, default=Path("config/collector.yaml"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--log-file",
        type=Path,
        action="append",
        default=[],
        help="Log file to include (repeatable).",
    )
    parser.add_argument("--stats-url", default=None)
    parser.add_argument(
        "--component-version",
        default=os.environ.get("GG_COMPONENT_VERSION", "unknown"),
    )
    args = parser.parse_args(argv)

    output = args.output or Path(
        f"support-bundle-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    )
    try:
        path = build_support_bundle(
            config_path=args.config,
            output_path=output,
            log_files=args.log_file,
            stats_url=args.stats_url,
            component_version=args.component_version,
        )
    except OSError as exc:
        print(f"support bundle failed: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
