"""OddsPapi client — correct score + half-time score (Betfair replacement)."""

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

from odds.api_client import _project_root, load_env_file
from odds.fast_mode import http_timeout
from odds.memory_cache import mem_get, mem_set

BASE_URL = "https://api.oddspapi.io/v4"
SOCCER_SPORT_ID = 10
DEFAULT_BOOKMAKERS = "pinnacle,bet365,unibet,williamhill,888sport,betway,sofascore,flashscore"
MARKETS_CACHE_TTL = 7 * 24 * 3600  # 7 days
FIXTURES_CACHE_TTL = 3 * 3600


@dataclass
class OddsPapiFetchResult:
    data: Any
    from_cache: bool


def get_oddspapi_key() -> str:
    load_env_file()
    key = os.environ.get("ODDSPAPI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ODDSPAPI_API_KEY non impostata. Registrati su https://oddspapi.io/ "
            "e aggiungi la key in .env — vedi docs/API_SETUP.md"
        )
    return key


def oddspapi_configured() -> bool:
    load_env_file()
    return bool(os.environ.get("ODDSPAPI_API_KEY", "").strip())


def _cache_dir() -> Path:
    path = _project_root() / "data" / "cache" / "oddspapi"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_json(path: str, params: dict[str, Any], cache_name: str, ttl: int) -> OddsPapiFetchResult:
    cache_file = _cache_dir() / cache_name
    mem_key = str(cache_file.resolve())
    cached = mem_get(mem_key, ttl)
    if cached is None and cache_file.exists():
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("fetched_at", 0)) <= ttl:
            cached = payload["data"]
            mem_set(mem_key, cached)
    if cached is not None:
        return OddsPapiFetchResult(data=cached, from_cache=True)

    params = {**params, "apiKey": get_oddspapi_key()}
    query = urllib.parse.urlencode(params)
    url = f"{BASE_URL}/{path}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FantamondialeFM/1.0 (Python; odds-fetch)",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=http_timeout(20)) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OddsPapi HTTP {exc.code} on /{path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OddsPapi request failed on /{path}: {exc}") from exc

    cache_file.write_text(
        json.dumps({"fetched_at": time.time(), "data": data}, indent=2),
        encoding="utf-8",
    )
    mem_set(mem_key, data)
    return OddsPapiFetchResult(data=data, from_cache=False)


def fetch_markets_catalog() -> list[dict[str, Any]]:
    result = _get_json(
        "markets",
        {"sportId": SOCCER_SPORT_ID, "language": "en"},
        "markets_soccer.json",
        MARKETS_CACHE_TTL,
    )
    if not isinstance(result.data, list):
        raise RuntimeError("Unexpected OddsPapi markets response")
    return result.data


def fetch_fixtures(from_iso: str, to_iso: str) -> list[dict[str, Any]]:
    result = _get_json(
        "fixtures",
        {
            "sportId": SOCCER_SPORT_ID,
            "from": from_iso,
            "to": to_iso,
            "statusId": 0,
            "hasOdds": "true",
            "bookmakers": "pinnacle",
        },
        f"fixtures_{from_iso[:10]}_{to_iso[:10]}.json",
        FIXTURES_CACHE_TTL,
    )
    if not isinstance(result.data, list):
        raise RuntimeError("Unexpected OddsPapi fixtures response")
    return result.data


def fetch_odds(fixture_id: str, bookmakers: str = DEFAULT_BOOKMAKERS) -> dict[str, Any]:
    result = _get_json(
        "odds",
        {"fixtureId": fixture_id, "bookmakers": bookmakers, "oddsFormat": "decimal"},
        f"odds_{fixture_id}_{bookmakers}.json",
        FIXTURES_CACHE_TTL,
    )
    if not isinstance(result.data, dict):
        raise RuntimeError("Unexpected OddsPapi odds response")
    return result.data
