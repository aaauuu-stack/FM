"""Dedupe hot lookups within one analysis (same thread pool workers)."""

from __future__ import annotations

import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")
_lock = threading.Lock()
_store: dict[str, Any] = {}


def cached_call(key: str, fn: Callable[[], T]) -> T:
    with _lock:
        if key in _store:
            return _store[key]
    value = fn()
    with _lock:
        _store[key] = value
    return value


def clear_request_cache() -> None:
    with _lock:
        _store.clear()
