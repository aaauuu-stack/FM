"""Parse Betfair markets into Fantamondiale MatchOdds fields."""

from __future__ import annotations

import re
from typing import Any

from odds.api_normalize import teams_match
from odds.betfair_client import list_market_book, list_market_catalogue, login
from odds.match_loader import MatchOdds

# Betfair market type codes (exact score markets)
MARKET_CORRECT_SCORE = "CORRECT_SCORE"
MARKET_HALF_TIME_SCORE = "HALF_TIME_SCORE"

# Runners like "Any Other Home Win" are excluded from de-vig
_ANY_OTHER_RE = re.compile(r"any other", re.I)
_SCORE_RE = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")


def parse_runner_score(name: str) -> tuple[int, int] | None:
    """Parse '1 - 0' or '2-1' into (home, away) goals."""
    if _ANY_OTHER_RE.search(name):
        return None
    match = _SCORE_RE.match(name.strip())
    if not match:
        return None
    home, away = int(match.group(1)), int(match.group(2))
    if home > 9 or away > 9:
        return None
    return home, away


def _best_back_price(runner: dict[str, Any]) -> float | None:
    ex = runner.get("ex") or {}
    backs = ex.get("availableToBack") or []
    if not backs:
        return None
    return float(backs[0]["price"])


def _runners_to_score_odds(market_book: dict[str, Any]) -> dict[str, float]:
    odds: dict[str, float] = {}
    for runner in market_book.get("runners", []):
        name = str(runner.get("runnerName", ""))
        score = parse_runner_score(name)
        if score is None:
            continue
        price = _best_back_price(runner)
        if price is None or price <= 1.0:
            continue
        key = f"{score[0]}-{score[1]}"
        odds[key] = price
    return odds


def _event_label(catalogue_item: dict[str, Any]) -> str:
    event = catalogue_item.get("event") or {}
    return str(event.get("name", ""))


def _pick_event_markets(
    catalogue: list[dict[str, Any]],
    home_query: str,
    away_query: str,
) -> dict[str, dict[str, Any]]:
    """Group catalogue entries by event and pick the matching fixture."""
    by_event: dict[str, list[dict[str, Any]]] = {}
    for item in catalogue:
        event = item.get("event") or {}
        event_id = str(event.get("id", ""))
        if not event_id:
            continue
        by_event.setdefault(event_id, []).append(item)

    for _event_id, items in by_event.items():
        label = _event_label(items[0])
        parts = re.split(r"\s+v(?:s)?\.?\s+", label, maxsplit=1, flags=re.I)
        if len(parts) != 2:
            continue
        ev_home, ev_away = parts[0].strip(), parts[1].strip()
        if teams_match(home_query, ev_home) and teams_match(away_query, ev_away):
            markets: dict[str, dict[str, Any]] = {}
            for item in items:
                desc = item.get("description") or {}
                mtype = str(desc.get("marketType", ""))
                market_name = str(item.get("marketName", ""))
                if mtype == MARKET_CORRECT_SCORE or "Correct Score" in market_name:
                    markets[MARKET_CORRECT_SCORE] = item
                elif mtype == MARKET_HALF_TIME_SCORE or "Half Time Score" in market_name:
                    markets[MARKET_HALF_TIME_SCORE] = item
            if markets:
                return markets

    labels = [_event_label(i) for i in catalogue[:10]]
    raise ValueError(
        f"Partita Betfair non trovata: {home_query} vs {away_query}. "
        f"Eventi visti: {', '.join(labels) if labels else '(nessuno)'}"
    )


def fetch_betfair_match_odds(home_query: str, away_query: str) -> MatchOdds:
    """
    Fetch CORRECT_SCORE and HALF_TIME_SCORE from Betfair for a match.

    Returns MatchOdds with correct_score and half_time_correct_score populated.
    """
    session = login()
    catalogue = list_market_catalogue(
        {
            "eventTypeIds": ["1"],
            "marketTypeCodes": [MARKET_CORRECT_SCORE, MARKET_HALF_TIME_SCORE],
            "textQuery": home_query,
        },
        max_results=200,
        session=session,
    )

    if not catalogue:
        raise ValueError(
            f"Nessun mercato Betfair per '{home_query}'. "
            "Il Mondiale potrebbe non essere ancora in calendario su Betfair."
        )

    markets = _pick_event_markets(catalogue, home_query, away_query)
    market_ids = [str(m["marketId"]) for m in markets.values()]
    books = list_market_book(market_ids, session=session)
    books_by_id = {str(b["marketId"]): b for b in books}

    odds = MatchOdds()

    cs_item = markets.get(MARKET_CORRECT_SCORE)
    if cs_item:
        cs_book = books_by_id.get(str(cs_item["marketId"]))
        if cs_book:
            odds.correct_score = _runners_to_score_odds(cs_book)

    ht_item = markets.get(MARKET_HALF_TIME_SCORE)
    if ht_item:
        ht_book = books_by_id.get(str(ht_item["marketId"]))
        if ht_book:
            odds.half_time_correct_score = _runners_to_score_odds(ht_book)

    if not odds.correct_score and not odds.half_time_correct_score:
        raise ValueError(
            f"Mercati Betfair trovati ma senza quote back per {home_query} vs {away_query}"
        )

    return odds
