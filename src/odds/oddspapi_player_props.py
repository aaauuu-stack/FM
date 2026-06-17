"""Player props from OddsPapi bookmaker odds (goalscorer, cards) — uses cached /odds payload."""

from __future__ import annotations

import statistics
from typing import Any

from odds.devig import proportional_devig
from odds.oddspapi_client import fetch_markets_catalog, fetch_odds, oddspapi_configured
from odds.oddspapi_normalize import lookup_oddspapi_fixture
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match

_GOAL_MARKET_TYPE = "players-anytimegoalscorer"
_CARD_MARKET_TYPE = "players-cards"


def discover_player_market_ids(catalog: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """Return (anytime_goalscorer_market_id, player_carded_yes_market_id)."""
    goal_id: int | None = None
    card_id: int | None = None

    for market in catalog:
        mtype = str(market.get("marketType", "")).lower()
        if mtype == _GOAL_MARKET_TYPE:
            goal_id = int(market["marketId"])
        elif mtype == _CARD_MARKET_TYPE and int(market.get("marketLength", 0)) == 1:
            card_id = int(market["marketId"])

    return goal_id, card_id


def extract_player_yes_probs(
    odds_payload: dict[str, Any],
    market_id: int,
) -> dict[str, float]:
    """Extract player -> de-vigged P(yes) from an OddsPapi player-prop market."""
    prices: dict[str, list[float]] = {}

    for book in (odds_payload.get("bookmakerOdds") or {}).values():
        if not book.get("bookmakerIsActive", True):
            continue
        market = (book.get("markets") or {}).get(str(market_id))
        if not market or not market.get("marketActive", True):
            continue
        for outcome in (market.get("outcomes") or {}).values():
            for pdata in (outcome.get("players") or {}).values():
                if not isinstance(pdata, dict) or not pdata.get("active", True):
                    continue
                name = str(pdata.get("playerName") or "").strip()
                price = float(pdata.get("price") or 0)
                if name and price > 1.0:
                    prices.setdefault(name, []).append(price)

    if not prices:
        return {}

    medians = {name: float(statistics.median(vals)) for name, vals in prices.items()}
    return proportional_devig(medians)


def fetch_oddspapi_player_props(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> tuple[dict[str, float], dict[str, float], str]:
    """Fetch goal + card probs from OddsPapi (reuses cached fixture odds)."""
    if not oddspapi_configured():
        return {}, {}, ""

    catalog = fetch_markets_catalog()
    goal_id, card_id = discover_player_market_ids(catalog)
    if goal_id is None and card_id is None:
        return {}, {}, "OddsPapi: mercati player prop assenti"

    fixture = lookup_oddspapi_fixture(home_query, away_query, kickoff_iso)
    odds_payload = fetch_odds(str(fixture["fixtureId"]))

    goal_probs = extract_player_yes_probs(odds_payload, goal_id) if goal_id else {}
    card_probs = extract_player_yes_probs(odds_payload, card_id) if card_id else {}

    parts: list[str] = []
    if goal_probs:
        parts.append(f"gol {len(goal_probs)}")
    if card_probs:
        parts.append(f"cartellini {len(card_probs)}")
    note = f"OddsPapi props ({', '.join(parts)})" if parts else "OddsPapi props: vuoto"
    return goal_probs, card_probs, note


def attach_oddspapi_player_props(
    roster: MatchRoster,
    kickoff_iso: str | None = None,
) -> tuple[MatchRoster, str]:
    """Merge OddsPapi bookmaker player props into roster."""
    goal_probs, card_probs, note = fetch_oddspapi_player_props(
        roster.home, roster.away, kickoff_iso
    )
    if not goal_probs and not card_probs:
        return roster, note

    g_hit = c_hit = 0
    updated: list[PlayerBonus] = []
    for player in roster.players:
        kwargs: dict[str, float] = {}
        for api_name, prob in goal_probs.items():
            if players_match(player.name, api_name):
                kwargs["p_goal"] = prob
                g_hit += 1
                break
        for api_name, prob in card_probs.items():
            if players_match(player.name, api_name):
                kwargs["p_yellow"] = prob
                c_hit += 1
                break
        updated.append(player.with_probs(**kwargs) if kwargs else player)

    roster.players = updated
    if g_hit or c_hit:
        note = f"{note}; matched gol={g_hit} cart={c_hit}"
    return roster, note
