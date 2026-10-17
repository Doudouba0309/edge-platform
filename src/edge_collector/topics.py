"""Topic naming for the frozen v1 telemetry namespace.

The scheme is deliberately minimal and protocol-neutral::

    edge/<gateway_id>/<device_id>/telemetry
    edge/<gateway_id>/status

``gateway_id`` is also the AWS IoT thing name, so it must be thing-name-safe.
``device_id`` is a logical asset id and must be safe as an MQTT topic level.
Both are immutable. Site, tenant, environment and asset metadata are carried in
the payload/registry, not in the topic, unless a real routing requirement is
proven. Reserved future classes are ``events`` and ``cmd``.
"""

from __future__ import annotations

from edge_collector.identifiers import validate_device_id, validate_gateway_id

TELEMETRY = "telemetry"
STATUS = "status"


def telemetry_topic(gateway_id: str, device_id: str) -> str:
    """Topic telemetry for one device is published to."""
    return (
        f"edge/{validate_gateway_id(gateway_id)}/"
        f"{validate_device_id(device_id)}/{TELEMETRY}"
    )


def status_topic(gateway_id: str) -> str:
    """Gateway liveness topic; the collector uses it as its MQTT Last Will."""
    return f"edge/{validate_gateway_id(gateway_id)}/{STATUS}"
