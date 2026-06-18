"""SofaScore scrape for player goal/card odds."""

from __future__ import annotations

import statistics
from typing import Any

from dataclasses import replace

from odds.devig import proportional_devig
from odds.scrape_sofascore import _choice_decimal, _market_name
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match

_GOALSCORER_HINTS = (
    "anytime goal",
    "anytime scorer",
    "goalscorer",
    "to score",
    "player to score",
)
_CARD_HINTS = (
    "to be carded",
    "player to be carded",
    "booking",
    "carded",
)
_FIRST_CARD_MARKET_HINTS = (
    "first player booked",
    "first player carded",
    "first to be carded",
    "1st player booked",
    "first booking",
)


def extract_goalscorer_from_sofa_markets(markets: list[dict[str, Any]]) -> dict[str, float]:
    """Parse anytime goalscorer odds from SofaScore /odds/1/all markets."""
    prices: dict[str, list[float]] = {}
    for market in markets:
        name = _market_name(market)
        if not any(h in name for h in _GOALSCORER_HINTS):
            continue
        if "first" in name or "last" in name:
            continue
        for choice in market.get("choices", []):
            label = str(choice.get("name") or choice.get("label") or "").strip()
            if not label or label.lower() in {"yes", "no"}:
                continue
            decimal = _choice_decimal(choice)
            if decimal is None:
                continue
            prices.setdefault(label, []).append(decimal)

    if not prices:
        return {}
    medians = {name: float(statistics.median(vals)) for name, vals in prices.items()}
    return proportional_devig(medians)


def extract_card_probs_from_sofa_markets(markets: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, list[float]] = {}
    for market in markets:
        name = _market_name(market)
        if not any(h in name for h in _CARD_HINTS):
            continue
        for choice in market.get("choices", []):
            label = str(choice.get("name") or choice.get("label") or "").strip()
            if not label or label.lower() in {"yes", "no", "over", "under"}:
                continue
            decimal = _choice_decimal(choice)
            if decimal is None:
                continue
            prices.setdefault(label, []).append(decimal)

    if not prices:
        return {}
    medians = {name: float(statistics.median(vals)) for name, vals in prices.items()}
    return proportional_devig(medians)


def extract_first_card_from_sofa_markets(markets: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, list[float]] = {}
    for market in markets:
        name = _market_name(market)
        if not any(h in name for h in _FIRST_CARD_MARKET_HINTS):
            continue
        for choice in market.get("choices", []):
            label = str(choice.get("name") or choice.get("label") or "").strip()
            if not label or label.lower() in {"yes", "no"}:
                continue
            decimal = _choice_decimal(choice)
            if decimal is None:
                continue
            prices.setdefault(label, []).append(decimal)
    if not prices:
        return {}
    medians = {n: float(statistics.median(v)) for n, v in prices.items()}
    return proportional_devig(medians)


def fetch_sofascore_player_props(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> tuple[dict[str, float], dict[str, float], dict, str]:
    """Player odds via SofaScore lite (one /odds/1/all, OddsPapi event id)."""
    from odds.sofascore_bundle import fetch_sofascore_bundle

    bundle = fetch_sofascore_bundle(
        home_query,
        away_query,
        kickoff_iso,
        need_match_cs=False,
        need_goal_props=True,
        need_card_props=True,
        need_first_card=False,
    )
    return (
        bundle.goal_probs or {},
        bundle.card_probs or {},
        {},
        bundle.props_note or "SofaScore: sofascoreId assente su OddsPapi",
    )


def attach_sofascore_player_probs(
    roster: MatchRoster,
    kickoff_iso: str | None = None,
    *,
    prefetched: tuple | None = None,
) -> tuple[MatchRoster, str]:
    """Merge SofaScore odds into roster (no Poisson, no stats NT)."""
    if prefetched is not None:
        goal_odds, card_odds, _, note = prefetched
    else:
        goal_odds, card_odds, _, note = fetch_sofascore_player_props(
            roster.home, roster.away, kickoff_iso
        )

    g_hit = c_hit = 0
    updated: list[PlayerBonus] = []
    for player in roster.players:
        kwargs: dict[str, float] = {}
        goal_hit = player.book_goal_matched
        card_hit = player.book_card_matched

        if float(player.p_goal or 0) <= 0:
            for api_name, prob in goal_odds.items():
                if players_match(player.name, api_name):
                    kwargs["p_goal"] = prob
                    g_hit += 1
                    goal_hit = True
                    break

        if player.p_yellow is None or float(player.p_yellow or 0) <= 0:
            for api_name, prob in card_odds.items():
                if players_match(player.name, api_name):
                    kwargs["p_yellow"] = prob
                    c_hit += 1
                    card_hit = True
                    break

        if kwargs:
            row = replace(
                player.with_probs(**kwargs),
                book_goal_matched=goal_hit,
                book_card_matched=card_hit,
            )
        else:
            row = player
        updated.append(row)

    roster.players = updated
    if g_hit or c_hit:
        note = f"{note}; matched quote_g={g_hit} quote_c={c_hit}"
    return roster, note
