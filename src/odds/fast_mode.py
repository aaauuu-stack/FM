"""Performance tuning only — never skips data sources (quality preserved)."""

from __future__ import annotations

import os


def is_cloud_host() -> bool:
    return bool(os.environ.get("RENDER"))


def is_fast_mode() -> bool:
    """Explicit opt-in for tighter HTTP timeouts (FM_FAST_MODE=1)."""
    return os.environ.get("FM_FAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def http_timeout(default: float) -> float:
    """Slightly shorter timeouts on cloud to fail fast and retry from cache."""
    if is_fast_mode():
        return min(default, 10.0)
    if is_cloud_host():
        return min(default, 15.0)
    return default
