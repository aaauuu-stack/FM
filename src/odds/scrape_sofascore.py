"""SofaScore odds source (correct score FT + 1T)."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

from odds.api_normalize import teams_match
from odds.match_loader import MatchOdds
from odds.oddspapi_client import oddspapi_configured
from odds.score_parsing import parse_score_outcome, score_key
from odds.scrape_client import fetch_json

SOFASCORE_ORIGIN = "https://www.sofascore.com"
FT_MARKET_HINTS = ("correct score", "exact score", "full time correct")
HT_MARKET_HINTS = ("1st half", "first half", "half time correct", "ht correct")


def _sofascore_headers() -> dict[str, str]:
    return {
        "Origin": SOFASCORE_ORIGIN,
        "Referer": f"{SOFASCORE_ORIGIN}/",
    }


def _kickoff_date(kickoff_iso: str | None) -> str:
    if kickoff_iso:
        try:
            kickoff = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
            return kickoff.date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _find_event(events: list[dict[str, Any]], home_query: str, away_query: str) -> dict[str, Any] | None:
    for event in events:
        home = str(event.get("homeTeam", {}).get("name", ""))
        away = str(event.get("awayTeam", {}).get("name", ""))
        if teams_match(home_query, home) and teams_match(away_query, away):
            return event
    return None


def _load_scheduled_events(day: str) -> list[dict[str, Any]]:
    urls = [
        f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{day}",
        f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{day}/inverse",
    ]
    events: list[dict[str, Any]] = []
    seen: set[int] = set()
    for url in urls:
        try:
            result = fetch_json(
                url,
                cache_name=f"sofascore_events_{day}_{url.split('/')[-1]}.json",
                extra_headers=_sofascore_headers(),
            )
        except RuntimeError:
            continue
        for event in result.data.get("events", []):
            event_id = int(event.get("id", 0))
            if event_id and event_id not in seen:
                seen.add(event_id)
                events.append(event)
    return events


def _choice_decimal(choice: dict[str, Any]) -> float | None:
    for key in ("decimalValue", "decimal", "price"):
        if key in choice and choice[key] is not None:
            value = float(choice[key])
            return value if value > 1.0 else None
    fractional = str(choice.get("fractionalValue", "")).strip()
    if "/" in fractional:
        num, den = fractional.split("/", 1)
        try:
            value = 1.0 + float(num) / float(den)
            return value if value > 1.0 else None
        except ValueError:
            return None
    return None


def _market_name(market: dict[str, Any]) -> str:
    return str(market.get("marketName") or market.get("name") or "").lower()


def _extract_ft_markets(markets: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, list[float]] = {}
    for market in markets:
        name = _market_name(market)
        if "half" in name or "1st" in name:
            continue
        if not any(hint in name for hint in FT_MARKET_HINTS):
            continue
        for choice in market.get("choices", []):
            label = str(choice.get("name") or choice.get("label") or "")
            score = parse_score_outcome(label.replace(":", "-"))
            if score is None:
                continue
            decimal = _choice_decimal(choice)
            if decimal is None:
                continue
            key = score_key(score[0], score[1])
            prices.setdefault(key, []).append(decimal)
    return {key: float(statistics.median(vals)) for key, vals in prices.items()}


def _extract_ht_markets(markets: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, list[float]] = {}
    for market in markets:
        name = _market_name(market)
        if not ("half" in name or "1st" in name):
            continue
        if "correct" not in name and "score" not in name:
            continue
        for choice in market.get("choices", []):
            label = str(choice.get("name") or choice.get("label") or "")
            score = parse_score_outcome(label.replace(":", "-"))
            if score is None:
                continue
            decimal = _choice_decimal(choice)
            if decimal is None:
                continue
            key = score_key(score[0], score[1])
            prices.setdefault(key, []).append(decimal)
    return {key: float(statistics.median(vals)) for key, vals in prices.items()}


def _extract_from_markets(
    markets: list[dict[str, Any]],
    hints: tuple[str, ...],
    *,
    exclude_half: bool = False,
) -> dict[str, float]:
    if exclude_half:
        return _extract_ft_markets(markets)
    if hints == HT_MARKET_HINTS:
        return _extract_ht_markets(markets)
    prices: dict[str, list[float]] = {}
    for market in markets:
        name = _market_name(market)
        if not any(hint in name for hint in hints):
            continue
        for choice in market.get("choices", []):
            label = str(choice.get("name") or choice.get("label") or "")
            score = parse_score_outcome(label.replace(":", "-"))
            if score is None:
                continue
            decimal = _choice_decimal(choice)
            if decimal is None:
                continue
            key = score_key(score[0], score[1])
            prices.setdefault(key, []).append(decimal)
    return {key: float(statistics.median(vals)) for key, vals in prices.items()}


def _sofascore_event_id(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None,
) -> int | None:
    if oddspapi_configured():
        try:
            from odds.oddspapi_normalize import lookup_oddspapi_fixture

            fixture = lookup_oddspapi_fixture(home_query, away_query, kickoff_iso)
            providers = fixture.get("externalProviders") or {}
            sofascore_id = providers.get("sofascoreId")
            if sofascore_id:
                return int(sofascore_id)
        except (RuntimeError, ValueError, TypeError):
            pass

    day = _kickoff_date(kickoff_iso)
    events = _load_scheduled_events(day)
    event = _find_event(events, home_query, away_query)
    return int(event["id"]) if event else None


def fetch_sofascore_match_odds(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> MatchOdds:
    event_id = _sofascore_event_id(home_query, away_query, kickoff_iso)
    if event_id is None:
        raise ValueError(f"Evento SofaScore non trovato per {home_query} vs {away_query}")

    odds_url = f"https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all"
    result = fetch_json(
        odds_url,
        cache_name=f"sofascore_odds_{event_id}.json",
        extra_headers=_sofascore_headers(),
    )
    markets = result.data.get("markets") or []
    if not markets:
        raise ValueError(f"SofaScore senza mercati quote per event {event_id}")

    ft = _extract_ft_markets(markets)
    ht = _extract_ht_markets(markets)
    if not ft and not ht:
        raise ValueError(f"SofaScore senza correct score per event {event_id}")

    return MatchOdds(correct_score=ft, half_time_correct_score=ht)
