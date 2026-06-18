"""SofaScore odds source (correct score FT + 1T)."""

from __future__ import annotations

import statistics
from typing import Any

from odds.match_loader import MatchOdds
from odds.score_parsing import parse_score_outcome, score_key

SOFASCORE_ORIGIN = "https://www.sofascore.com"
FT_MARKET_HINTS = ("correct score", "exact score", "full time correct")
HT_MARKET_HINTS = ("1st half", "first half", "half time correct", "ht correct")


def _sofascore_headers() -> dict[str, str]:
    return {
        "Origin": SOFASCORE_ORIGIN,
        "Referer": f"{SOFASCORE_ORIGIN}/",
    }


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


def fetch_sofascore_match_odds(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
    *,
    event_id: int | None = None,
) -> MatchOdds:
    from odds.sofascore_bundle import (
        fetch_sofascore_match_odds_from_event,
        sofascore_event_id_from_oddspapi,
    )

    resolved = event_id or sofascore_event_id_from_oddspapi(
        home_query, away_query, kickoff_iso
    )
    if resolved is None:
        raise ValueError(
            f"SofaScore CS: sofascoreId assente su OddsPapi per {home_query} vs {away_query}"
        )
    return fetch_sofascore_match_odds_from_event(resolved)
