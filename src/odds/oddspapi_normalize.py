"""Parse OddsPapi odds into MatchOdds (correct score FT + 1T)."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from odds.api_normalize import teams_match
from odds.match_loader import MatchOdds
from odds.oddspapi_client import (
    SOCCER_SPORT_ID,
    fetch_fixtures,
    fetch_markets_catalog,
    fetch_odds,
)
from odds.score_parsing import parse_score_outcome, score_key


def _discover_market_ids(catalog: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """Return (ft_correct_score_market_id, ht_correct_score_market_id) for soccer."""
    ft_id: int | None = None
    ht_id: int | None = None

    for market in catalog:
        if int(market.get("sportId", 0)) != SOCCER_SPORT_ID:
            continue
        if str(market.get("marketType", "")).lower() != "correctscore":
            continue

        market_id = int(market["marketId"])
        period = str(market.get("period", "")).lower()
        name = str(market.get("marketName", "")).lower()

        if period == "p1" or "first half" in name or "1st half" in name:
            ht_id = market_id
        elif period == "fulltime" and "second half" not in name:
            ft_id = market_id

    return ft_id, ht_id


def _outcome_names_for_market(catalog: list[dict[str, Any]], market_id: int) -> dict[int, str]:
    for market in catalog:
        if int(market["marketId"]) == market_id:
            return {
                int(o["outcomeId"]): str(o.get("outcomeName", ""))
                for o in market.get("outcomes", [])
            }
    return {}


def _extract_market_odds(
    odds_payload: dict[str, Any],
    market_id: int,
    catalog: list[dict[str, Any]],
) -> dict[str, float]:
    """Extract score -> decimal price from all bookmakers in the payload."""
    name_map = _outcome_names_for_market(catalog, market_id)
    bookmaker_odds = odds_payload.get("bookmakerOdds") or {}
    prices: dict[str, list[float]] = {}

    for book in bookmaker_odds.values():
        market = (book.get("markets") or {}).get(str(market_id))
        if not market:
            continue
        for oid_str, outcome in (market.get("outcomes") or {}).items():
            outcome_name = str(outcome.get("outcomeName") or name_map.get(int(oid_str), ""))
            score = parse_score_outcome(outcome_name)
            if score is None:
                continue
            players = outcome.get("players") or {}
            player0 = players.get("0") or players.get(0)
            if not player0 or not player0.get("active"):
                continue
            price = float(player0.get("price", 0))
            if price <= 1.0:
                continue
            key = score_key(score[0], score[1])
            prices.setdefault(key, []).append(price)

    return {key: float(statistics.median(vals)) for key, vals in prices.items()}


def _find_fixture(fixtures: list[dict[str, Any]], home_query: str, away_query: str) -> dict[str, Any]:
    world_cup = [
        f
        for f in fixtures
        if str(f.get("tournamentSlug", "")).lower() == "world-cup"
        or str(f.get("tournamentName", "")).lower() == "world cup"
    ]
    search_pool = world_cup or fixtures

    for fixture in search_pool:
        home = str(fixture.get("participant1Name", ""))
        away = str(fixture.get("participant2Name", ""))
        if teams_match(home_query, home) and teams_match(away_query, away):
            return fixture

    sample = [
        f"{f.get('participant1Name')} vs {f.get('participant2Name')}" for f in fixtures[:8]
    ]
    raise ValueError(
        f"Fixture OddsPapi non trovato: {home_query} vs {away_query}. "
        f"Disponibili (campione): {', '.join(sample) if sample else '(nessuno)'}"
    )


def lookup_oddspapi_fixture(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> dict[str, Any]:
    """Find OddsPapi fixture metadata for a match."""
    if kickoff_iso:
        try:
            kickoff = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
        except ValueError:
            kickoff = datetime.now(timezone.utc)
    else:
        kickoff = datetime.now(timezone.utc)

    from_iso = (kickoff - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = (kickoff + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fixtures = fetch_fixtures(from_iso, to_iso)
    return _find_fixture(fixtures, home_query, away_query)


def fetch_oddspapi_match_odds(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> MatchOdds:
    """Fetch FT + HT correct score for a fixture."""
    if kickoff_iso:
        try:
            kickoff = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
        except ValueError:
            kickoff = datetime.now(timezone.utc)
    else:
        kickoff = datetime.now(timezone.utc)

    from_iso = (kickoff - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = (kickoff + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")

    catalog = fetch_markets_catalog()
    ft_market_id, ht_market_id = _discover_market_ids(catalog)
    if ft_market_id is None:
        raise ValueError("Mercato 'Correct Score' non trovato nel catalogo OddsPapi")

    fixture = lookup_oddspapi_fixture(home_query, away_query, kickoff_iso)
    fixture_id = str(fixture["fixtureId"])

    odds_payload = fetch_odds(fixture_id)
    result = MatchOdds(
        correct_score=_extract_market_odds(odds_payload, ft_market_id, catalog)
    )

    if ht_market_id is not None:
        result.half_time_correct_score = _extract_market_odds(
            odds_payload, ht_market_id, catalog
        )

    if not result.correct_score:
        raise ValueError(f"Nessuna quota correct score per fixture {fixture_id}")

    return result
