#!/usr/bin/env python3
"""Subscribe to the smoke topics and append every message as JSONL.

Kept in Python so the subscriber reconnects across the deliberate broker outage
in scripts/smoke-local.sh; mosquitto_sub exits on the first disconnect.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8883)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--client-id", default="edge-platform-smoke-subscriber")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def _on_connect(
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any = None,
    ) -> None:
        if reason_code.is_failure:
            print(f"connect failed: {reason_code}", flush=True)
            return
        client.subscribe("edge/+/+/telemetry", qos=1)
        client.subscribe("edge/+/status", qos=1)
        print("subscribed", flush=True)

    def _on_message(
        client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage
    ) -> None:
        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError:
            payload = message.payload.decode("utf-8", errors="replace")
        with out.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"topic": message.topic, "payload": payload}) + "\n"
            )
            handle.flush()
        print(f"message {message.topic}", flush=True)

    client = mqtt.Client(
        CallbackAPIVersion.VERSION2,
        client_id=args.client_id,
        protocol=mqtt.MQTTv311,
    )
    client.tls_set(ca_certs=args.ca, certfile=args.cert, keyfile=args.key)
    client.tls_insecure_set(False)
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect_async(args.host, args.port, keepalive=30)
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
