"""Fast analysis on cloud (Render): skip slow SofaScore/OddsPapi scrapes."""

from __future__ import annotations

import os


def is_fast_mode() -> bool:
    if os.environ.get("FM_FAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return bool(os.environ.get("RENDER"))


def http_timeout(default: float) -> float:
    return 8.0 if is_fast_mode() else default
