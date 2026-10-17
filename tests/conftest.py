"""Shared fixtures for the contract tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

import pytest

from edge_collector.models import (
    Batch,
    Quality,
    Sample,
    SourceKind,
    utcnow,
)


@pytest.fixture
def make_batch() -> Callable[..., Batch]:
    """Build a valid, per-device batch with deterministic content."""

    def _make(
        *,
        seq: int = 1,
        samples: int = 2,
        gateway_id: str = "gw-factory-7",
        device_id: str = "plc-line-1",
        produced_at: datetime | None = None,
    ) -> Batch:
        timestamp = produced_at or utcnow()
        sample_models = [
            Sample(
                device_id=device_id,
                metric=f"metric_{i}",
                value=20.0 + i,
                ts=timestamp,
                source=SourceKind.OPCUA,
                origin=f"ns=2;s=Line1.Metric{i}",
                unit="degC",
                quality=Quality.GOOD,
                tags={"line": "1"},
            )
            for i in range(samples)
        ]
        return Batch(
            gateway_id=gateway_id,
            device_id=device_id,
            seq=seq,
            produced_at=timestamp,
            samples=sample_models,
        )

    return _make
