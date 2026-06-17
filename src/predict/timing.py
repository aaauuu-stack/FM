"""Per-step timings for diagnosing slow analysis (logged + shown on timeout)."""

from __future__ import annotations

import time
from contextlib import contextmanager

_timings: dict[str, float] = {}


def reset_timings() -> None:
    _timings.clear()


@contextmanager
def timed(step: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        _timings[step] = time.perf_counter() - t0


def timing_summary() -> str:
    if not _timings:
        return "nessun dato timing"
    parts = [f"{name}={sec:.1f}s" for name, sec in sorted(_timings.items(), key=lambda x: -x[1])]
    return ", ".join(parts)
