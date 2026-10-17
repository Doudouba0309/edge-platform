"""Identifier grammar shared by the models and the topic builders.

Gateway ids become AWS IoT thing names, so they use the thing-name alphabet.
Device ids live only in topic levels, so they may also contain ``.``. Both are
immutable, ASCII, and free of MQTT wildcards and separators.
"""

from __future__ import annotations

import re

GATEWAY_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$"
DEVICE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"

_GATEWAY_ID = re.compile(GATEWAY_ID_PATTERN)
_DEVICE_ID = re.compile(DEVICE_ID_PATTERN)


def validate_gateway_id(value: str) -> str:
    if not _GATEWAY_ID.fullmatch(value):
        raise ValueError(
            f"invalid gateway_id {value!r}: must match {GATEWAY_ID_PATTERN!r}"
        )
    return value


def validate_device_id(value: str) -> str:
    if not _DEVICE_ID.fullmatch(value):
        raise ValueError(
            f"invalid device_id {value!r}: must match {DEVICE_ID_PATTERN!r}"
        )
    return value
