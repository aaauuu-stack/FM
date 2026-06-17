"""Single OddsPapi fixture fetch — match CS, player props, first card."""

from __future__ import annotations

from dataclasses import dataclass

from odds.match_loader import MatchOdds
from odds.oddspapi_client import fetch_markets_catalog, fetch_odds, oddspapi_configured
from odds.oddspapi_normalize import (
    _discover_market_ids,
    _extract_market_odds,
    lookup_oddspapi_fixture,
)
from odds.oddspapi_player_props import discover_player_market_ids, extract_player_yes_probs
from odds.event_kl_model import _discover_first_card_market_id


@dataclass
class OddsPapiBundle:
    match_odds: MatchOdds | None = None
    goal_probs: dict[str, float] | None = None
    card_probs: dict[str, float] | None = None
    props_note: str = ""
    first_card_probs: dict[str, float] | None = None
    first_card_note: str = ""


def fetch_oddspapi_bundle(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
    *,
    need_match_cs: bool = True,
    need_props: bool = True,
    need_first_card: bool = True,
) -> OddsPapiBundle:
    """One catalog + fixture + odds payload for all OddsPapi markets."""
    bundle = OddsPapiBundle()
    if not oddspapi_configured():
        return bundle

    catalog = fetch_markets_catalog()
    fixture = lookup_oddspapi_fixture(home_query, away_query, kickoff_iso)
    payload = fetch_odds(str(fixture["fixtureId"]))

    if need_match_cs:
        ft_market_id, ht_market_id = _discover_market_ids(catalog)
        if ft_market_id is not None:
            match = MatchOdds(
                correct_score=_extract_market_odds(payload, ft_market_id, catalog)
            )
            if ht_market_id is not None:
                match.half_time_correct_score = _extract_market_odds(
                    payload, ht_market_id, catalog
                )
            if match.correct_score:
                bundle.match_odds = match

    if need_props:
        goal_id, card_id = discover_player_market_ids(catalog)
        goal_probs = extract_player_yes_probs(payload, goal_id) if goal_id else {}
        card_probs = extract_player_yes_probs(payload, card_id) if card_id else {}
        bundle.goal_probs = goal_probs
        bundle.card_probs = card_probs
        parts: list[str] = []
        if goal_probs:
            parts.append(f"gol {len(goal_probs)}")
        if card_probs:
            parts.append(f"cartellini {len(card_probs)}")
        bundle.props_note = (
            f"OddsPapi props ({', '.join(parts)})" if parts else "OddsPapi props: vuoto"
        )

    if need_first_card:
        market_id = _discover_first_card_market_id(catalog)
        if market_id:
            probs = extract_player_yes_probs(payload, market_id)
            if probs:
                bundle.first_card_probs = probs
                bundle.first_card_note = f"OddsPapi first card ({len(probs)})"

    return bundle
