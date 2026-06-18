"""HTTP fetch for web odds sources (cache + browser-like client)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odds.api_client import _project_root
from odds.fast_mode import http_timeout
from odds.memory_cache import mem_get, mem_set

DEFAULT_CACHE_TTL = 3 * 3600
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8",
}


@dataclass
class ScrapeFetchResult:
    data: Any
    from_cache: bool


def _cache_dir() -> Path:
    path = _project_root() / "data" / "cache" / "scrape"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_cache(cache_file: Path, ttl: int) -> Any | None:
    if not cache_file.exists():
        return None
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    if time.time() - float(payload.get("fetched_at", 0)) > ttl:
        return None
    return payload.get("data")


def _write_cache(cache_file: Path, data: Any) -> None:
    cache_file.write_text(
        json.dumps({"fetched_at": time.time(), "data": data}, indent=2),
        encoding="utf-8",
    )


def _fetch_live(
    url: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    data: bytes | None = None,
) -> bytes:
    """GET/POST with curl_cffi when installed, else urllib."""
    timeout = http_timeout(25.0)
    try:
        from curl_cffi import requests as cffi_requests

        if method == "POST":
            response = cffi_requests.post(
                url,
                headers=headers,
                data=data,
                impersonate="chrome120",
                timeout=timeout,
            )
        else:
            response = cffi_requests.get(
                url, headers=headers, impersonate="chrome120", timeout=timeout
            )
        response.raise_for_status()
        return response.content
    except ImportError:
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()


def fetch_text(
    url: str,
    *,
    cache_name: str,
    ttl: int = DEFAULT_CACHE_TTL,
    extra_headers: dict[str, str] | None = None,
    method: str = "GET",
    body: bytes | None = None,
) -> ScrapeFetchResult:
    """Fetch HTML/text with disk cache."""
    cache_file = _cache_dir() / cache_name
    mem_key = f"text:{cache_file.resolve()}"
    cached = mem_get(mem_key, ttl)
    if cached is None:
        cached = _read_cache(cache_file, ttl)
        if cached is not None:
            mem_set(mem_key, cached)
    if cached is not None:
        return ScrapeFetchResult(data=cached, from_cache=True)

    headers = {
        **BROWSER_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        **(extra_headers or {}),
    }
    try:
        raw = _fetch_live(url, headers, method=method, data=body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Scrape HTTP {exc.code} on {url}: {detail[:240]}") from exc
    except Exception as exc:
        if exc.__class__.__name__ == "HTTPError":
            raise RuntimeError(f"Scrape HTTP error on {url}: {exc}") from exc
        raise RuntimeError(f"Scrape request failed on {url}: {exc}") from exc

    text = raw.decode("utf-8", errors="replace")
    _write_cache(cache_file, text)
    mem_set(mem_key, text)
    return ScrapeFetchResult(data=text, from_cache=False)


def fetch_json(
    url: str,
    *,
    cache_name: str,
    ttl: int = DEFAULT_CACHE_TTL,
    extra_headers: dict[str, str] | None = None,
) -> ScrapeFetchResult:
    cache_file = _cache_dir() / cache_name
    mem_key = str(cache_file.resolve())
    cached = mem_get(mem_key, ttl)
    if cached is None:
        cached = _read_cache(cache_file, ttl)
        if cached is not None:
            mem_set(mem_key, cached)
    if cached is not None:
        return ScrapeFetchResult(data=cached, from_cache=True)

    headers = {**BROWSER_HEADERS, **(extra_headers or {})}
    try:
        raw = _fetch_live(url, headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Scrape HTTP {exc.code} on {url}: {detail[:240]}") from exc
    except Exception as exc:
        if exc.__class__.__name__ == "HTTPError":
            raise RuntimeError(f"Scrape HTTP error on {url}: {exc}") from exc
        raise RuntimeError(f"Scrape request failed on {url}: {exc}") from exc

    data = json.loads(raw.decode("utf-8"))
    _write_cache(cache_file, data)
    mem_set(mem_key, data)
    return ScrapeFetchResult(data=data, from_cache=False)
