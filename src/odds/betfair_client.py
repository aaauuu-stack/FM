"""Betfair Exchange API client (login, market catalogue, prices)."""

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

DEFAULT_SSO_URL = "https://identitysso.betfair.com/api/login"
DEFAULT_API_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"
SESSION_TTL_SECONDS = 6 * 60 * 60  # 6 hours


@dataclass
class BetfairSession:
    token: str
    fetched_at: float


def get_betfair_config() -> dict[str, str]:
    """Load Betfair credentials from environment."""
    load_env_file()
    app_key = os.environ.get("BETFAIR_APP_KEY", "").strip()
    username = os.environ.get("BETFAIR_USERNAME", "").strip()
    password = os.environ.get("BETFAIR_PASSWORD", "").strip()
    if not app_key or not username or not password:
        raise RuntimeError(
            "Betfair non configurato. Imposta BETFAIR_APP_KEY, BETFAIR_USERNAME e "
            "BETFAIR_PASSWORD in .env — vedi docs/API_SETUP.md"
        )
    return {
        "app_key": app_key,
        "username": username,
        "password": password,
        "sso_url": os.environ.get("BETFAIR_SSO_URL", DEFAULT_SSO_URL).strip(),
        "api_url": os.environ.get("BETFAIR_API_URL", DEFAULT_API_URL).strip(),
    }


def betfair_configured() -> bool:
    load_env_file()
    return all(
        os.environ.get(k, "").strip()
        for k in ("BETFAIR_APP_KEY", "BETFAIR_USERNAME", "BETFAIR_PASSWORD")
    )


def _session_cache_path() -> Path:
    path = _project_root() / "data" / "cache" / "betfair"
    path.mkdir(parents=True, exist_ok=True)
    return path / "session.json"


def _load_cached_session() -> BetfairSession | None:
    cache = _session_cache_path()
    if not cache.exists():
        return None
    raw = json.loads(cache.read_text(encoding="utf-8"))
    session = BetfairSession(token=str(raw["token"]), fetched_at=float(raw["fetched_at"]))
    if time.time() - session.fetched_at > SESSION_TTL_SECONDS:
        return None
    return session


def _save_session(session: BetfairSession) -> None:
    _session_cache_path().write_text(
        json.dumps({"token": session.token, "fetched_at": session.fetched_at}),
        encoding="utf-8",
    )


def login(force: bool = False) -> BetfairSession:
    """Authenticate and return session token."""
    if not force:
        cached = _load_cached_session()
        if cached:
            return cached

    cfg = get_betfair_config()
    body = urllib.parse.urlencode({"username": cfg["username"], "password": cfg["password"]}).encode()
    request = urllib.request.Request(
        cfg["sso_url"],
        data=body,
        headers={
            "X-Application": cfg["app_key"],
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Betfair login HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Betfair login failed: {exc}") from exc

    status = str(payload.get("status", "")).upper()
    if status != "SUCCESS":
        error = payload.get("error") or payload.get("loginStatus") or payload
        raise RuntimeError(f"Betfair login rejected: {error}")

    token = str(payload.get("token", "")).strip()
    if not token:
        raise RuntimeError(f"Betfair login: token mancante nella risposta: {payload}")

    session = BetfairSession(token=token, fetched_at=time.time())
    _save_session(session)
    return session


def api_post(endpoint: str, body: dict[str, Any], session: BetfairSession | None = None) -> Any:
    """POST to Betfair Exchange REST API."""
    cfg = get_betfair_config()
    sess = session or login()
    url = f"{cfg['api_url'].rstrip('/')}/{endpoint.strip('/')}/"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "X-Application": cfg["app_key"],
            "X-Authentication": sess.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Betfair API {endpoint} HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Betfair API {endpoint} failed: {exc}") from exc


def list_market_catalogue(
    market_filter: dict[str, Any],
    *,
    max_results: int = 100,
    market_projection: list[str] | None = None,
    session: BetfairSession | None = None,
) -> list[dict[str, Any]]:
    body = {
        "filter": market_filter,
        "maxResults": str(max_results),
        "marketProjection": market_projection
        or ["EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME", "COMPETITION"],
    }
    result = api_post("listMarketCatalogue", body, session=session)
    if not isinstance(result, list):
        raise RuntimeError(f"Unexpected listMarketCatalogue response: {result!r}")
    return result


def list_market_book(
    market_ids: list[str],
    session: BetfairSession | None = None,
) -> list[dict[str, Any]]:
    if not market_ids:
        return []
    body = {
        "marketIds": market_ids,
        "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
    }
    result = api_post("listMarketBook", body, session=session)
    if not isinstance(result, list):
        raise RuntimeError(f"Unexpected listMarketBook response: {result!r}")
    return result
