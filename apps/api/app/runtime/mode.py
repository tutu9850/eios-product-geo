"""Side-effect controls for a sealed GEO baseline runtime."""
from __future__ import annotations

import os


BASELINE_MODE = "baseline"


def runtime_mode() -> str:
    return os.environ.get("GEO_RUNTIME_MODE", "production").strip().lower() or "production"


def is_baseline_mode() -> bool:
    """True only for the sealed, no-background-work baseline profile."""
    return runtime_mode() == BASELINE_MODE


class OutboundNetworkBlocked(RuntimeError):
    """Raised when a sealed baseline attempts to reach an external dependency."""


def require_outbound_network(operation: str) -> None:
    """Fail explicitly instead of silently using a live dependency in baseline mode."""
    if is_baseline_mode():
        raise OutboundNetworkBlocked(f"outbound_network_blocked:{operation}")
