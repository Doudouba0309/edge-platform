"""CLI entry point: ``python -m edge_collector`` or ``edge-collector``."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from edge_collector.app import CollectorApp
from edge_collector.config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="edge-collector",
        description="Edge Platform telemetry collector",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="YAML configuration file (default: config/collector.yaml)",
    )
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        parser.error(str(exc))

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        asyncio.run(CollectorApp(cfg).run())
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        logging.getLogger(__name__).error("collector failed to start: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
