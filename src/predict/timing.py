"""Per-step timings for diagnosing slow analysis (logged + shown on timeout)."""

from __future__ import annotations

import time
from contextlib import contextmanager

_timings: dict[str, float] = {}
_progress: str = ""
_started_at: float | None = None


def reset_timings() -> None:
    _timings.clear()
    global _progress, _started_at
    _progress = ""
    _started_at = time.perf_counter()


def set_progress(msg: str) -> None:
    global _progress
    _progress = msg


def elapsed_total() -> float:
    if _started_at is None:
        return 0.0
    return time.perf_counter() - _started_at


@contextmanager
def timed(step: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        _timings[step] = time.perf_counter() - t0


def timing_summary() -> str:
    parts = [f"{name}={sec:.1f}s" for name, sec in sorted(_timings.items(), key=lambda x: -x[1])]
    if _progress:
        parts.append(f"progress={_progress}")
    if not parts:
        return "nessun dato timing"
    return ", ".join(parts)
