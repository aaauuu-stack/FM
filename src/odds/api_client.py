"""The Odds API client with local file cache."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odds.fast_mode import http_timeout
from odds.memory_cache import mem_get, mem_set

DEFAULT_BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_SPORT = "soccer_fifa_world_cup"
DEFAULT_REGION = "eu"
DEFAULT_MARKETS = "h2h,totals"
DEFAULT_MARKETS_EXTENDED = "h2h,totals,h2h_h1,btts"
DEFAULT_CACHE_TTL_SECONDS = 3 * 60 * 60  # 3 hours


@dataclass
class FetchResult:
    events: list[dict[str, Any]]
    from_cache: bool
    cache_path: Path | None
    requests_remaining: str | None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from .env into os.environ (without overwriting)."""
    env_path = path or (_project_root() / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_api_key() -> str:
    load_env_file()
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ODDS_API_KEY not set. Copy .env.example to .env and add your key from https://the-odds-api.com/"
        )
    return key


def _cache_dir() -> Path:
    path = _project_root() / "data" / "cache" / "odds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(sport: str, region: str, markets: str) -> Path:
    safe_markets = markets.replace(",", "_")
    return _cache_dir() / f"{sport}_{region}_{safe_markets}.json"


def _read_cache(path: Path, ttl_seconds: int) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    fetched_at = float(payload.get("fetched_at", 0))
    if time.time() - fetched_at > ttl_seconds:
        return None
    return payload.get("events", [])


def _write_cache(path: Path, events: list[dict[str, Any]], headers: dict[str, str]) -> None:
    payload = {
        "fetched_at": time.time(),
        "requests_remaining": headers.get("x-requests-remaining"),
        "events": events,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def fetch_odds(
    *,
    sport: str = DEFAULT_SPORT,
    region: str = DEFAULT_REGION,
    markets: str = DEFAULT_MARKETS,
    api_key: str | None = None,
    force_refresh: bool = False,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> FetchResult:
    """
    Fetch upcoming/live odds from The Odds API.

    Uses a local JSON cache to avoid burning API credits on repeated runs.
    """
    key = api_key or get_api_key()
    cache_file = _cache_path(sport, region, markets)

    mem_key = str(cache_file.resolve())
    if not force_refresh:
        cached = mem_get(mem_key, cache_ttl_seconds)
        if cached is None:
            cached = _read_cache(cache_file, cache_ttl_seconds)
            if cached is not None:
                mem_set(mem_key, cached)
        if cached is not None:
            remaining = None
            if cache_file.exists():
                try:
                    remaining = json.loads(cache_file.read_text()).get("requests_remaining")
                except json.JSONDecodeError:
                    pass
            return FetchResult(
                events=cached,
                from_cache=True,
                cache_path=cache_file,
                requests_remaining=str(remaining) if remaining else None,
            )

    params = urllib.parse.urlencode(
        {
            "apiKey": key,
            "regions": region,
            "markets": markets,
            "oddsFormat": "decimal",
        }
    )
    url = f"{DEFAULT_BASE_URL}/sports/{sport}/odds/?{params}"

    try:
        with urllib.request.urlopen(url, timeout=http_timeout(30)) as response:
            body = response.read().decode("utf-8")
            headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"The Odds API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"The Odds API request failed: {exc}") from exc

    events = json.loads(body)
    if not isinstance(events, list):
        raise RuntimeError("Unexpected Odds API response (expected a list of events)")

    _write_cache(cache_file, events, headers)
    mem_set(mem_key, events)

    return FetchResult(
        events=events,
        from_cache=False,
        cache_path=cache_file,
        requests_remaining=headers.get("x-requests-remaining"),
    )


@dataclass
class EventOddsResult:
    event: dict[str, Any]
    from_cache: bool
    cache_path: Path | None
    requests_remaining: str | None


def _event_cache_path(event_id: str, region: str, markets: str) -> Path:
    safe_markets = markets.replace(",", "_")
    return _cache_dir() / f"event_{event_id}_{region}_{safe_markets}.json"


def fetch_event_odds(
    event_id: str,
    *,
    sport: str = DEFAULT_SPORT,
    region: str = DEFAULT_REGION,
    markets: str,
    api_key: str | None = None,
    force_refresh: bool = False,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> EventOddsResult:
    """
    Fetch player props / extra markets for a single event.

    Uses local cache — one API credit per uncached event+markets combo.
    """
    key = api_key or get_api_key()
    cache_file = _event_cache_path(event_id, region, markets)

    mem_key = str(cache_file.resolve())
    if not force_refresh:
        cached = mem_get(mem_key, cache_ttl_seconds)
        if cached is None:
            cached = _read_cache(cache_file, cache_ttl_seconds)
            if cached is not None:
                mem_set(mem_key, cached)
        if cached is not None and cached:
            event = cached[0] if isinstance(cached, list) else cached
            remaining = None
            try:
                remaining = json.loads(cache_file.read_text()).get("requests_remaining")
            except json.JSONDecodeError:
                pass
            return EventOddsResult(
                event=event,
                from_cache=True,
                cache_path=cache_file,
                requests_remaining=str(remaining) if remaining else None,
            )

    params = urllib.parse.urlencode(
        {
            "apiKey": key,
            "regions": region,
            "markets": markets,
            "oddsFormat": "decimal",
        }
    )
    url = f"{DEFAULT_BASE_URL}/sports/{sport}/events/{event_id}/odds?{params}"

    try:
        with urllib.request.urlopen(url, timeout=http_timeout(30)) as response:
            body = response.read().decode("utf-8")
            headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"The Odds API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"The Odds API request failed: {exc}") from exc

    event = json.loads(body)
    if not isinstance(event, dict):
        raise RuntimeError("Unexpected Odds API event-odds response")

    _write_cache(cache_file, [event], headers)
    mem_set(mem_key, [event])

    return EventOddsResult(
        event=event,
        from_cache=False,
        cache_path=cache_file,
        requests_remaining=headers.get("x-requests-remaining"),
    )
