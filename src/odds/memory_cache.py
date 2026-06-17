"""In-process cache layered on disk JSON caches (thread-safe)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def mem_get(key: str, ttl_seconds: float) -> Any | None:
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        fetched_at, value = entry
        if time.time() - fetched_at > ttl_seconds:
            del _store[key]
            return None
        return value


def mem_set(key: str, value: Any) -> None:
    with _lock:
        _store[key] = (time.time(), value)


def warm_json_cache_dir(cache_dir: Path, ttl_seconds: int) -> int:
    """Load fresh on-disk cache files into memory (e.g. on web startup)."""
    if not cache_dir.is_dir():
        return 0
    loaded = 0
    now = time.time()
    for path in cache_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(payload.get("fetched_at", 0))
            if now - fetched_at > ttl_seconds:
                continue
            if "events" in payload:
                data = payload["events"]
            elif "data" in payload:
                data = payload["data"]
            else:
                data = payload
            mem_set(str(path.resolve()), data)
            loaded += 1
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return loaded


def warm_all_caches(project_root: Path) -> int:
    """Warm odds + scrape disk caches into memory."""
    odds_dir = project_root / "data" / "cache" / "odds"
    scrape_dir = project_root / "data" / "cache" / "scrape"
    ttl = 3 * 3600
    return warm_json_cache_dir(odds_dir, ttl) + warm_json_cache_dir(scrape_dir, ttl)
