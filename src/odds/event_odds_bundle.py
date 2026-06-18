"""Combined The Odds API event-odds fetch (goalscorer + player props)."""

from __future__ import annotations

import statistics

from odds.api_client import fetch_event_odds
from odds.devig import independent_implied_probs
from odds.goalscorer import GOALSCORER_MARKET, _collect_goalscorer_prices
from odds.player_props import PLAYER_PROP_MARKETS, _parse_event_player_props


def fetch_combined_event_player_odds(
    event_id: str,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
) -> tuple[dict[str, float], dict[str, dict[str, float]] | None]:
    """One API call for goalscorer + card/red player props."""
    markets = f"{GOALSCORER_MARKET},{PLAYER_PROP_MARKETS}"
    try:
        result = fetch_event_odds(
            event_id,
            sport=sport,
            region=region,
            markets=markets,
            force_refresh=force_refresh,
        )
        payload = result.event
    except RuntimeError:
        return {}, None

    raw_gs = _collect_goalscorer_prices(payload)
    goalscorer: dict[str, float] = {}
    if raw_gs:
        medians = {n: float(statistics.median(v)) for n, v in raw_gs.items()}
        goalscorer = independent_implied_probs(medians)

    event_props = _parse_event_player_props(payload)
    return goalscorer, event_props
