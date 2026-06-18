"""SofaScore goalkeeper fallback when lineup API returns 403."""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urlparse

from odds.scrape_client import fetch_text
from players.lineup_web_search import _duckduckgo_results, _fetch_page_text

_GK_IN_GOAL = re.compile(
    r"(?:with|anchored by)\s+([A-Za-z\u00c0-\u024f\.\- ]+?)\s+in goal",
    re.IGNORECASE,
)
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL,
)
_MAX_NEWS_PROBES = 12


def _slugify(name: str) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    ascii_name = ascii_name.replace("&", " ").replace("'", " ")
    ascii_name = re.sub(r"\band\b", " ", ascii_name, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def _team_in_sentence(sentence: str, team_name: str) -> bool:
    parts = re.split(r"[\s&]+", team_name.lower())
    tokens = {t for t in parts if len(t) >= 3}
    lower = sentence.lower()
    return any(token in lower for token in tokens)


def parse_gk_starters_from_sofa_text(
    text: str,
    *,
    home_team: str,
    away_team: str,
) -> tuple[set[str], set[str]]:
    """Parse 'Kobel in goal' style sentences from SofaScore news/preview HTML."""
    home_gk: set[str] = set()
    away_gk: set[str] = set()
    for sentence in re.split(r"[.!?\n]", text):
        if "in goal" not in sentence.lower():
            continue
        match = _GK_IN_GOAL.search(sentence)
        if not match:
            continue
        gk_name = match.group(1).strip()
        if not gk_name:
            continue
        if _team_in_sentence(sentence, home_team):
            home_gk.add(gk_name)
        elif _team_in_sentence(sentence, away_team):
            away_gk.add(gk_name)
    return home_gk, away_gk


def _event_meta_from_page(event_id: int) -> dict | None:
    url = f"https://www.sofascore.com/event/{event_id}"
    try:
        result = fetch_text(
            url,
            cache_name=f"sofascore_event_page_{event_id}.html",
        )
    except RuntimeError:
        return None
    match = _NEXT_DATA.search(result.data)
    if not match:
        return None
    try:
        event = json.loads(match.group(1))["props"]["pageProps"]["event"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    home = event.get("homeTeam") or {}
    away = event.get("awayTeam") or {}
    home_name = str(home.get("name") or home.get("shortName") or "").strip()
    away_name = str(away.get("name") or away.get("shortName") or "").strip()
    if not home_name or not away_name:
        return None
    return {
        "home": home_name,
        "away": away_name,
        "slug": str(event.get("slug") or "").strip(),
    }


def _news_stems(home: str, away: str, *, match_slug: str = "") -> list[str]:
    hs, asl = _slugify(home), _slugify(away)
    stems = [
        f"{hs}-vs-{asl}",
        f"{hs}-versus-{asl}",
        f"{hs}-vs-{asl.replace('-and-', '-')}",
    ]
    if match_slug:
        compact = match_slug.replace("-and-", "-")
        stems.append(f"{compact.replace('-', '-vs-', 1)}" if "-vs-" not in compact else compact)
        if "vs" not in match_slug:
            parts = match_slug.split("-", 1)
            if len(parts) == 2:
                stems.append(f"{parts[0]}-vs-{parts[1].replace('-and-', '-')}")
    seen: set[str] = set()
    ordered: list[str] = []
    for stem in stems:
        if stem and stem not in seen:
            seen.add(stem)
            ordered.append(stem)
    return ordered


def _candidate_news_urls(home: str, away: str, *, match_slug: str = "") -> list[str]:
    tails = (
        "group-b-pregame-at-sofi",
        "group-a-pregame",
        "group-c-pregame",
        "group-d-pregame",
        "group-e-pregame",
        "group-f-pregame",
        "group-g-pregame",
        "group-h-pregame",
        "pregame",
        "predicted-lineup",
        "lineups",
        "preview",
        "match-preview",
    )
    urls: list[str] = []
    seen: set[str] = set()
    for stem in _news_stems(home, away, match_slug=match_slug):
        for tail in tails:
            slug = f"{stem}-{tail}"
            if slug in seen:
                continue
            seen.add(slug)
            urls.append(f"https://www.sofascore.com/news/{slug}")
            if len(urls) >= _MAX_NEWS_PROBES:
                return urls
    return urls


def _sofascore_news_urls(home: str, away: str, *, match_slug: str = "") -> list[str]:
    urls = _candidate_news_urls(home, away, match_slug=match_slug)
    query = f"site:sofascore.com/news {home} {away} pregame lineup"
    seen = {urlparse(u).path for u in urls}
    for url, _snippet in _duckduckgo_results(query):
        if "sofascore.com/news/" not in url:
            continue
        path = urlparse(url).path.rstrip("/")
        if not path.startswith("/news/") or path in seen:
            continue
        seen.add(path)
        urls.append(f"https://www.sofascore.com{path}")
    return urls


def fetch_gk_starters_from_sofascore_web(event_id: int) -> tuple[set[str], set[str], str]:
    """
    Read starting GKs from SofaScore news/preview pages when lineup API is blocked.

    Still SofaScore-sourced — not book/heuristic fallback.
    """
    meta = _event_meta_from_page(event_id)
    if not meta:
        return set(), set(), ""

    home_team = meta["home"]
    away_team = meta["away"]
    home_gk: set[str] = set()
    away_gk: set[str] = set()

    for url in _sofascore_news_urls(
        home_team,
        away_team,
        match_slug=meta.get("slug", ""),
    ):
        page = _fetch_page_text(url)
        if not page or "in goal" not in page.lower():
            continue
        h, a = parse_gk_starters_from_sofa_text(
            page,
            home_team=home_team,
            away_team=away_team,
        )
        home_gk |= h
        away_gk |= a
        if home_gk and away_gk:
            break

    if not home_gk and not away_gk:
        return set(), set(), ""

    note_parts: list[str] = []
    if home_gk:
        note_parts.append(f"casa {sorted(home_gk)[0]}")
    if away_gk:
        note_parts.append(f"ospite {sorted(away_gk)[0]}")
    return home_gk, away_gk, "SofaScore news (" + ", ".join(note_parts) + ")"
