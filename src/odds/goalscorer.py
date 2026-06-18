"""Player goal probabilities: OddsPapi/SofaScore scrape, API, Poisson last resort."""

from __future__ import annotations

import math
import statistics
from typing import Any

from dataclasses import replace

from odds.api_client import fetch_odds
from odds.api_normalize import find_event
from odds.devig import proportional_devig
from odds.oddspapi_player_props import attach_oddspapi_player_props
from odds.player_events import attach_event_probs
from odds.player_props import attach_player_props_from_api, apply_event_player_props
from odds.scrape_sofascore_players import attach_sofascore_player_probs
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match
from players.team_data import get_player_stats

GOALSCORER_MARKET = "player_goal_scorer_anytime"

_ROLE_GOAL_WEIGHT = {"FWD": 3.0, "MID": 1.0, "DEF": 0.2, "GK": 0.0}


def _collect_goalscorer_prices(event: dict[str, Any]) -> dict[str, list[float]]:
    prices: dict[str, list[float]] = {}
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != GOALSCORER_MARKET:
                continue
            for outcome in market.get("outcomes", []):
                name = str(outcome.get("name", "")).strip()
                price = float(outcome.get("price", 0))
                if name and price > 1.0:
                    prices.setdefault(name, []).append(price)
    return prices


def apply_goalscorer_probs(
    roster: MatchRoster,
    probs: dict[str, float],
) -> tuple[MatchRoster, str]:
    """Fill p_goal on roster from pre-fetched goalscorer probabilities."""
    if not probs:
        return roster, "goalscorer: mercato vuoto per questa partita"

    updated: list[PlayerBonus] = []
    matched = 0
    for player in roster.players:
        p_goal = 0.0
        hit = False
        for api_name, prob in probs.items():
            if players_match(player.name, api_name):
                p_goal = prob
                matched += 1
                hit = True
                break
        row = player.with_probs(p_goal=p_goal)
        if hit:
            row = replace(row, book_goal_matched=True)
            updated.append(row)
        else:
            updated.append(player)

    roster.players = updated
    return roster, f"goalscorer API ({matched}/{len(roster.players)} matched)"


def fetch_goalscorer_probabilities(
    home_query: str,
    away_query: str,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
) -> dict[str, float]:
    """Return player name -> de-vigged P(anytime goalscorer)."""
    result = fetch_odds(
        sport=sport,
        region=region,
        markets=GOALSCORER_MARKET,
        force_refresh=force_refresh,
    )
    event = find_event(result.events, home_query, away_query)
    raw_prices = _collect_goalscorer_prices(event)
    if not raw_prices:
        return {}

    medians = {name: float(statistics.median(vals)) for name, vals in raw_prices.items()}
    return proportional_devig(medians)


def attach_goalscorer_odds(
    roster: MatchRoster,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
) -> tuple[MatchRoster, str]:
    """Fill p_goal on roster players from The Odds API bulk endpoint."""
    try:
        probs = fetch_goalscorer_probabilities(
            roster.home,
            roster.away,
            sport=sport,
            region=region,
            force_refresh=force_refresh,
        )
    except (RuntimeError, ValueError) as exc:
        return roster, f"goalscorer non disponibile: {exc}"

    return apply_goalscorer_probs(roster, probs)


def estimate_team_expected_goals(match) -> tuple[float, float]:
    """Expected FT goals per team from match Poisson distribution."""
    from odds.distribution import build_distribution

    dist = build_distribution(match)
    lambda_home = sum(h * prob for (h, a), prob in dist.ft_marginal.items())
    lambda_away = sum(a * prob for (h, a), prob in dist.ft_marginal.items())
    return float(lambda_home), float(lambda_away)


def _team_name_for_side(roster: MatchRoster, side: str) -> str:
    return roster.home if side == "home" else roster.away


def _player_goal_weight(player: PlayerBonus, roster: MatchRoster) -> float:
    """Weight for Poisson goal share: stats NT > ruolo+bonus FM."""
    team = _team_name_for_side(roster, player.side)
    stats = get_player_stats(team, player.name)
    if stats and stats.goals_per90 > 0:
        # Bonus FM basso = attaccante più probabile (regolamento §8.3)
        fm_factor = 1.0 + (12.0 - min(player.bonus_goal, 12)) / 12.0
        minutes_factor = stats.minutes_expected / 90.0
        return stats.goals_per90 * fm_factor * minutes_factor

    base = _ROLE_GOAL_WEIGHT.get(player.role.upper(), 1.0)
    if base <= 0:
        return 0.0
    # Bonus FM basso = titolare / attaccante più probabile (come path stats NT)
    fm_factor = 1.0 + (12.0 - min(player.bonus_goal, 12)) / 12.0
    return base * fm_factor


def attach_poisson_goal_estimates(roster: MatchRoster, match) -> MatchRoster:
    """Estimate P(goal) from team xG + national stats / role weights."""
    lambda_home, lambda_away = estimate_team_expected_goals(match)
    team_lambda = {"home": lambda_home, "away": lambda_away}

    weights: dict[str, float] = {"home": 0.0, "away": 0.0}
    for player in roster.players:
        weights[player.side] += _player_goal_weight(player, roster)

    updated: list[PlayerBonus] = []
    for player in roster.players:
        if player.is_goalkeeper or float(player.p_goal or 0.0) > 0:
            updated.append(player)
            continue
        w = _player_goal_weight(player, roster)
        side_total = weights[player.side]
        if w <= 0 or side_total <= 0:
            p_goal = 0.0
        else:
            share = w / side_total
            lam_player = team_lambda[player.side] * share
            p_goal = 1.0 - math.exp(-lam_player)
        updated.append(player.with_probs(p_goal=p_goal))

    roster.players = updated
    return roster


def _roster_needs_goal_fill(roster: MatchRoster) -> bool:
    """True if any outfield player still lacks P(gol)."""
    return any(
        not p.is_goalkeeper and float(p.p_goal or 0.0) <= 0 for p in roster.players
    )


def attach_goal_probs(
    roster: MatchRoster,
    match,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
    goalscorer_probs: dict[str, float] | None = None,
    event_player_props: dict[str, dict[str, float]] | None = None,
) -> tuple[MatchRoster, str]:
    """Fill missing P(gol) per giocatore: API, poi Poisson solo sui vuoti."""
    notes: list[str] = []

    if _roster_needs_goal_fill(roster):
        if goalscorer_probs is not None:
            roster, bulk_note = apply_goalscorer_probs(roster, goalscorer_probs)
        else:
            roster, bulk_note = attach_goalscorer_odds(
                roster, sport=sport, region=region, force_refresh=force_refresh
            )
        notes.append(bulk_note)

    if _roster_needs_goal_fill(roster):
        if event_player_props is not None:
            roster, props_note = apply_event_player_props(roster, event_player_props)
        else:
            roster, props_note = attach_player_props_from_api(
                roster, sport=sport, region=region, force_refresh=force_refresh
            )
        if props_note:
            notes.append(props_note)

    if _roster_needs_goal_fill(roster):
        roster = attach_poisson_goal_estimates(roster, match)
        notes.append("Poisson ultimo fallback (solo giocatori senza quota gol)")

    if not notes:
        return roster, "P(gol) gia da quote/scrape per tutti"
    return roster, "; ".join(notes)


def estimate_clean_sheet_probs_from_match(match) -> tuple[float, float]:
    """Estimate P(home CS) and P(away CS) from match odds via Poisson."""
    from odds.distribution import build_distribution

    dist = build_distribution(match)
    p_home_cs = sum(prob for (h, a), prob in dist.ft_marginal.items() if a == 0)
    p_away_cs = sum(prob for (h, a), prob in dist.ft_marginal.items() if h == 0)
    return float(p_home_cs), float(p_away_cs)


def attach_clean_sheet_probs(roster: MatchRoster, match) -> MatchRoster:
    p_home_cs, p_away_cs = estimate_clean_sheet_probs_from_match(match)
    updated: list[PlayerBonus] = []
    for player in roster.players:
        if not (player.is_goalkeeper and player.starter):
            updated.append(player)
            continue
        p_cs = p_home_cs if player.side == "home" else p_away_cs
        updated.append(player.with_probs(p_clean_sheet=p_cs))
    roster.players = updated
    return roster


def attach_all_player_probs(
    roster: MatchRoster,
    match,
    *,
    sport: str,
    region: str,
    force_refresh: bool = False,
    use_oddspapi: bool = True,
    use_scrape: bool = True,
    oddspapi_props: tuple[dict[str, float], dict[str, float], str] | None = None,
    sofa_props: tuple | None = None,
    goalscorer_probs: dict[str, float] | None = None,
    event_player_props: dict[str, dict[str, float]] | None = None,
) -> tuple[MatchRoster, str]:
    """Attach player probs: OddsPapi + SofaScore scrape, API, rigoristi, malus."""
    notes: list[str] = []
    kickoff = roster.kickoff or getattr(match, "kickoff", None)

    if use_oddspapi:
        roster, oddspapi_note = attach_oddspapi_player_props(
            roster, kickoff, prefetched=oddspapi_props
        )
        if oddspapi_note:
            notes.append(oddspapi_note)

    if use_scrape:
        roster, sofa_note = attach_sofascore_player_probs(
            roster, kickoff, prefetched=sofa_props
        )
        if sofa_note:
            notes.append(sofa_note)

    roster, goal_note = attach_goal_probs(
        roster,
        match,
        sport=sport,
        region=region,
        force_refresh=force_refresh,
        goalscorer_probs=goalscorer_probs,
        event_player_props=event_player_props,
    )
    notes.append(goal_note)

    roster = attach_event_probs(roster, match)
    return roster, " | ".join(notes)
