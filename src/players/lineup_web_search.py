"""Web search fallback for probable lineups when SofaScore API is unavailable."""

from __future__ import annotations

import hashlib
import html
import os
import re
from urllib.parse import quote_plus, unquote, urlparse

from odds.scrape_client import fetch_text
from players.models import MatchRoster, PlayerBonus
from players.name_match import normalize_player, players_match

_MIN_NAMES_PER_SIDE = 6
_MAX_PAGES = 2
_DDG_URL = "https://html.duckduckgo.com/html/"


def web_search_enabled() -> bool:
    flag = os.environ.get("FM_LINEUP_WEB_SEARCH", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _cache_slug(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _duckduckgo_results(query: str) -> list[tuple[str, str]]:
    """Return (url, snippet) from DuckDuckGo HTML search."""
    body = f"q={quote_plus(query)}".encode("utf-8")
    cache_name = f"ddg_lineup_{_cache_slug(query)}.json"
    result = fetch_text(
        _DDG_URL,
        cache_name=cache_name,
        method="POST",
        body=body,
        extra_headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    page = result.data
    if not isinstance(page, str):
        return []

    hits: list[tuple[str, str]] = []
    for block in re.findall(
        r'class="result__body".*?</div>\s*</div>',
        page,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        link_match = re.search(
            r'class="result__a"[^>]*href="([^"]+)"',
            block,
            flags=re.IGNORECASE,
        )
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|span|div)>',
            block,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not link_match:
            continue
        raw_url = html.unescape(link_match.group(1))
        if "uddg=" in raw_url:
            qs = urlparse(raw_url).query
            for part in qs.split("&"):
                if part.startswith("uddg="):
                    raw_url = unquote(part.split("=", 1)[1])
                    break
        snippet = html.unescape(re.sub(r"<[^>]+>", " ", snippet_match.group(1) if snippet_match else ""))
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if raw_url and snippet:
            hits.append((raw_url, snippet))
    return hits


def _fetch_page_text(url: str) -> str:
    host = urlparse(url).netloc.replace(".", "_") or "page"
    cache_name = f"lineup_page_{host}_{_cache_slug(url)}.json"
    try:
        result = fetch_text(url, cache_name=cache_name)
    except RuntimeError:
        return ""
    if isinstance(result.data, str):
        return re.sub(r"\s+", " ", html.unescape(result.data))
    return ""


def _player_in_text(player: PlayerBonus, text: str) -> bool:
    norm_text = normalize_player(text)
    if not norm_text:
        return False
    tokens = set(norm_text.split())
    norm_name = normalize_player(player.name)
    if not norm_name:
        return False
    if norm_name in norm_text:
        return True
    name_tokens = norm_name.split()
    last = name_tokens[-1]
    if len(last) >= 4 and last in tokens:
        return True
    for chunk in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.\s'-]{2,40}", text):
        if players_match(player.name, chunk):
            return True
    return False


def _names_in_corpus(players: list[PlayerBonus], corpus: str) -> set[str]:
    found: set[str] = set()
    for player in players:
        if _player_in_text(player, corpus):
            found.add(player.name)
    return found


def _collect_corpus(home: str, away: str) -> str:
    queries = [
        f"{home} {away} probabile formazione titolari",
        f"{home} vs {away} predicted lineup starters",
        f"{home} probabile formazione titolari",
        f"{away} probabile formazione titolari",
    ]
    parts: list[str] = []
    seen_urls: set[str] = set()
    for query in queries:
        for url, snippet in _duckduckgo_results(query):
            parts.append(snippet)
            if url in seen_urls or len(seen_urls) >= _MAX_PAGES:
                continue
            seen_urls.add(url)
            page_text = _fetch_page_text(url)
            if page_text:
                parts.append(page_text[:12000])
    return "\n".join(parts)


def fetch_lineups_web_search(
    roster: MatchRoster,
) -> tuple[set[str], set[str], str]:
    """
    Search the web for probable lineups and match names against the FM roster.

    Returns starter name sets per side (FM names). Empty sets on failure.
    """
    if not web_search_enabled():
        return set(), set(), ""

    try:
        corpus = _collect_corpus(roster.home, roster.away)
    except RuntimeError:
        return set(), set(), ""
    if not corpus.strip():
        return set(), set(), ""

    home_players = roster.home_players()
    away_players = roster.away_players()
    home_names = _names_in_corpus(home_players, corpus)
    away_names = _names_in_corpus(away_players, corpus)

    notes: list[str] = []
    if len(home_names) >= _MIN_NAMES_PER_SIDE:
        notes.append(f"web {len(home_names)} casa")
    else:
        home_names = set()
    if len(away_names) >= _MIN_NAMES_PER_SIDE:
        notes.append(f"web {len(away_names)} ospite")
    else:
        away_names = set()

    if not notes:
        return set(), set(), ""

    return home_names, away_names, "ricerca online (" + ", ".join(notes) + ")"
