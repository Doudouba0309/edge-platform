#!/usr/bin/env python3
"""Validate the JSONL captured by scripts/smoke_subscriber.py."""

from __future__ import annotations

import json
import pathlib
import sys

from jsonschema import Draft202012Validator

from edge_collector.schema import load_schema, repo_schema_path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_validate.py <capture.jsonl>", file=sys.stderr)
        return 2

    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        print(f"no capture file at {path}", file=sys.stderr)
        return 1

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    telemetry = [record for record in records if record["topic"].endswith("/telemetry")]
    status = [record for record in records if record["topic"].endswith("/status")]

    if not telemetry:
        print("no telemetry records", file=sys.stderr)
        return 1
    if not status:
        print("no status records", file=sys.stderr)
        return 1
    if not any(record["payload"] == "online" for record in status):
        print("no online status record", file=sys.stderr)
        return 1

    validator = Draft202012Validator(load_schema(repo_schema_path()))
    for record in telemetry:
        payload = record["payload"]
        validator.validate(payload)
        expected = f"edge/{payload['gateway_id']}/{payload['device_id']}/telemetry"
        if record["topic"] != expected:
            print(
                f"topic/payload mismatch: {record['topic']} != {expected}",
                file=sys.stderr,
            )
            return 1

    print(f"validated {len(telemetry)} telemetry record(s) and {len(status)} status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
