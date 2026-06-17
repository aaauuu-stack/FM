"""Per-event player props from The Odds API (goalscorer, cards) with cache."""

from __future__ import annotations

import statistics
from typing import Any

from odds.api_client import fetch_event_odds, fetch_odds
from odds.api_normalize import find_event
from odds.devig import proportional_devig
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match

GOAL_MARKET = "player_goal_scorer_anytime"
CARD_MARKET = "player_to_receive_card"
RED_CARD_MARKET = "player_to_receive_red_card"

PLAYER_PROP_MARKETS = f"{GOAL_MARKET},{CARD_MARKET},{RED_CARD_MARKET}"


def _collect_yes_prices(event: dict[str, Any], market_key: str) -> dict[str, list[float]]:
    """Collect Yes prices keyed by player name (from name or description field)."""
    prices: dict[str, list[float]] = {}
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                label = str(
                    outcome.get("description") or outcome.get("name") or ""
                ).strip()
                if not label or label.lower() in {"yes", "no", "over", "under"}:
                    continue
                if str(outcome.get("name", "")).lower() == "no":
                    continue
                price = float(outcome.get("price", 0))
                if price > 1.0:
                    prices.setdefault(label, []).append(price)
    return prices


def _devig_props(raw: dict[str, list[float]]) -> dict[str, float]:
    if not raw:
        return {}
    medians = {name: float(statistics.median(vals)) for name, vals in raw.items()}
    return proportional_devig(medians)


def _parse_event_player_props(payload: dict[str, Any]) -> dict[str, dict[str, float]] | None:
    goal_raw = _collect_yes_prices(payload, GOAL_MARKET)
    card_raw = _collect_yes_prices(payload, CARD_MARKET)
    red_raw = _collect_yes_prices(payload, RED_CARD_MARKET)

    if not goal_raw and not card_raw and not red_raw:
        return None

    return {
        "goal": _devig_props(goal_raw),
        "card": _devig_props(card_raw),
        "red": _devig_props(red_raw),
    }


def fetch_event_player_props_by_id(
    event_id: str,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
) -> dict[str, dict[str, float]] | None:
    """Fetch per-event player props using a known event id (no extra listing call)."""
    try:
        result = fetch_event_odds(
            event_id,
            sport=sport,
            region=region,
            markets=PLAYER_PROP_MARKETS,
            force_refresh=force_refresh,
        )
        return _parse_event_player_props(result.event)
    except RuntimeError:
        return None


def _fetch_event_player_props(
    home_query: str,
    away_query: str,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
) -> dict[str, dict[str, float]] | None:
    """Try event-odds endpoint for player props (1 API call, cached)."""
    try:
        listing = fetch_odds(
            sport=sport,
            region=region,
            markets="h2h",
            force_refresh=False,
        )
        event = find_event(listing.events, home_query, away_query)
        event_id = str(event.get("id", ""))
        if not event_id:
            return None

        result = fetch_event_odds(
            event_id,
            sport=sport,
            region=region,
            markets=PLAYER_PROP_MARKETS,
            force_refresh=force_refresh,
        )
        payload = result.event
    except (RuntimeError, ValueError):
        return None

    return _parse_event_player_props(payload)


def apply_event_player_props(
    roster: MatchRoster,
    props: dict[str, dict[str, float]],
) -> tuple[MatchRoster, str]:
    """Merge pre-fetched per-event player props into roster."""
    if not props:
        return roster, ""

    g_matched = c_matched = r_matched = 0
    updated: list[PlayerBonus] = []
    for player in roster.players:
        kwargs: dict[str, float] = {}
        for api_name, prob in props.get("goal", {}).items():
            if players_match(player.name, api_name):
                kwargs["p_goal"] = prob
                g_matched += 1
                break
        for api_name, prob in props.get("card", {}).items():
            if players_match(player.name, api_name):
                kwargs["p_yellow"] = prob
                c_matched += 1
                break
        for api_name, prob in props.get("red", {}).items():
            if players_match(player.name, api_name):
                kwargs["p_red"] = prob
                r_matched += 1
                break
        updated.append(player.with_probs(**kwargs) if kwargs else player)

    roster.players = updated
    parts = []
    if g_matched:
        parts.append(f"props gol {g_matched}")
    if c_matched:
        parts.append(f"props cartellini {c_matched}")
    if r_matched:
        parts.append(f"props rossi {r_matched}")
    if not parts:
        return roster, "props API: mercato vuoto"
    return roster, "props API (" + ", ".join(parts) + ")"


def attach_player_props_from_api(
    roster: MatchRoster,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
) -> tuple[MatchRoster, str]:
    """Merge per-event player props when bookmakers expose them."""
    props = _fetch_event_player_props(
        roster.home,
        roster.away,
        sport=sport,
        region=region,
        force_refresh=force_refresh,
    )
    if not props:
        return roster, ""

    return apply_event_player_props(roster, props)
