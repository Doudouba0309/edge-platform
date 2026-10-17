"""Source extension point.

Every source owns its own task and its own reconnection policy. It normalises
its protocol into :class:`~edge_collector.models.Sample` and hands samples to a
non-blocking emit callback; it never batches, spools or publishes.
"""

from __future__ import annotations

from collections.abc import Callable

from edge_collector.models import Sample

EmitFn = Callable[[Sample], None]

__all__ = ["EmitFn"]
