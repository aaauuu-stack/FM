"""SofaScore scrape for player goal/card rates and goalscorer odds."""

from __future__ import annotations

import math
import statistics
from typing import Any

from odds.devig import proportional_devig
from odds.scrape_client import fetch_json
from odds.scrape_sofascore import _sofascore_event_id, _sofascore_headers, _choice_decimal
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match
from players.team_data import PlayerStatProfile, card_prob_from_per90, default_minutes_for_role

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


def _market_name(market: dict[str, Any]) -> str:
    return str(market.get("marketName") or market.get("name") or "").lower()


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


def _fetch_event_teams(event_id: int) -> tuple[int, int] | None:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    result = fetch_json(
        url,
        cache_name=f"sofascore_event_{event_id}.json",
        extra_headers=_sofascore_headers(),
    )
    event = result.data.get("event") or result.data
    home_id = int((event.get("homeTeam") or {}).get("id") or 0)
    away_id = int((event.get("awayTeam") or {}).get("id") or 0)
    if home_id and away_id:
        return home_id, away_id
    return None


def _parse_player_statistics(raw: dict[str, Any]) -> PlayerStatProfile | None:
    stats = raw.get("statistics") or raw.get("stats") or {}
    if not isinstance(stats, dict):
        return None

    appearances = float(stats.get("appearances") or stats.get("matches") or 0)
    minutes = float(stats.get("minutesPlayed") or stats.get("minutes") or 0)
    goals = float(stats.get("goals") or 0)
    yellow = float(stats.get("yellowCards") or stats.get("yellow") or 0)
    red = float(stats.get("redCards") or stats.get("red") or 0)

    if minutes <= 0 and appearances > 0:
        minutes = appearances * 85.0
    if minutes <= 0:
        return None

    mins90 = minutes / 90.0
    return PlayerStatProfile(
        goals_per90=goals / mins90 if goals else 0.0,
        yellow_per90=yellow / mins90 if yellow else 0.0,
        red_per90=red / mins90 if red else 0.0,
        minutes_expected=min(90.0, minutes / max(appearances, 1)),
    )


def fetch_sofascore_team_player_stats(team_id: int) -> dict[str, PlayerStatProfile]:
    """Scrape squad list + season stats for a national team."""
    url = f"https://api.sofascore.com/api/v1/team/{team_id}/players"
    result = fetch_json(
        url,
        cache_name=f"sofascore_team_players_{team_id}.json",
        extra_headers=_sofascore_headers(),
    )
    players = result.data.get("players") or []
    out: dict[str, PlayerStatProfile] = {}
    for entry in players:
        if not isinstance(entry, dict):
            continue
        player = entry.get("player") or {}
        name = str(player.get("name") or player.get("shortName") or "").strip()
        if not name:
            continue
        profile = _parse_player_statistics(entry)
        if profile:
            out[name] = profile
    return out


def _goal_prob_from_profile(profile: PlayerStatProfile, role: str) -> float:
    minutes = profile.minutes_expected or default_minutes_for_role(role)
    rate = profile.goals_per90 * (minutes / 90.0)
    return min(0.85, 1.0 - math.exp(-rate)) if rate > 0 else 0.0


def fetch_sofascore_player_props(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, PlayerStatProfile], str]:
    """
    Scrape SofaScore for player odds + squad stats.

    Returns (goal_probs, card_probs, stats_by_name, note).
    """
    event_id = _sofascore_event_id(home_query, away_query, kickoff_iso)
    if event_id is None:
        return {}, {}, {}, "SofaScore: evento non trovato"

    notes: list[str] = []
    goal_probs: dict[str, float] = {}
    card_probs: dict[str, float] = {}
    stats: dict[str, PlayerStatProfile] = {}

    try:
        odds_url = f"https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all"
        odds_result = fetch_json(
            odds_url,
            cache_name=f"sofascore_odds_{event_id}.json",
            extra_headers=_sofascore_headers(),
        )
        markets = odds_result.data.get("markets") or []
        goal_probs = extract_goalscorer_from_sofa_markets(markets)
        card_probs = extract_card_probs_from_sofa_markets(markets)
        if goal_probs:
            notes.append(f"quote gol {len(goal_probs)}")
        if card_probs:
            notes.append(f"quote cartellini {len(card_probs)}")
    except RuntimeError as exc:
        notes.append(f"quote: {exc}")

    try:
        teams = _fetch_event_teams(event_id)
        if teams:
            home_id, away_id = teams
            for team_id in (home_id, away_id):
                team_stats = fetch_sofascore_team_player_stats(team_id)
                stats.update(team_stats)
            if stats:
                notes.append(f"stats NT {len(stats)} giocatori")
    except RuntimeError as exc:
        notes.append(f"stats: {exc}")

    note = "SofaScore scrape (" + ", ".join(notes) + ")" if notes else "SofaScore: nessun dato"
    return goal_probs, card_probs, stats, note


def attach_sofascore_player_probs(
    roster: MatchRoster,
    kickoff_iso: str | None = None,
    *,
    prefetched: tuple | None = None,
) -> tuple[MatchRoster, str]:
    """Merge SofaScore odds + scraped NT stats into roster (no Poisson)."""
    if prefetched is not None:
        goal_odds, card_odds, stats, note = prefetched
    else:
        goal_odds, card_odds, stats, note = fetch_sofascore_player_props(
            roster.home, roster.away, kickoff_iso
        )

    g_hit = c_hit = s_hit = 0
    updated: list[PlayerBonus] = []
    for player in roster.players:
        kwargs: dict[str, float] = {}

        if float(player.p_goal or 0) <= 0:
            for api_name, prob in goal_odds.items():
                if players_match(player.name, api_name):
                    kwargs["p_goal"] = prob
                    g_hit += 1
                    break
            if "p_goal" not in kwargs and stats:
                for stat_name, profile in stats.items():
                    if players_match(player.name, stat_name):
                        p = _goal_prob_from_profile(profile, player.role)
                        if p > 0:
                            kwargs["p_goal"] = p
                            s_hit += 1
                        break

        if player.p_yellow is None or float(player.p_yellow or 0) <= 0:
            for api_name, prob in card_odds.items():
                if players_match(player.name, api_name):
                    kwargs["p_yellow"] = prob
                    c_hit += 1
                    break
            if "p_yellow" not in kwargs and stats:
                for stat_name, profile in stats.items():
                    if players_match(player.name, stat_name):
                        minutes = profile.minutes_expected or default_minutes_for_role(
                            player.role
                        )
                        if profile.yellow_per90 > 0:
                            kwargs["p_yellow"] = card_prob_from_per90(
                                profile.yellow_per90, minutes
                            )
                        if profile.red_per90 > 0:
                            kwargs["p_red"] = card_prob_from_per90(
                                profile.red_per90, minutes
                            )
                        break

        updated.append(player.with_probs(**kwargs) if kwargs else player)

    roster.players = updated
    if g_hit or c_hit or s_hit:
        note = f"{note}; matched quote_g={g_hit} quote_c={c_hit} stats={s_hit}"
    return roster, note
