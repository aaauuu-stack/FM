"""Player event probabilities: rigoristi ufficiali, stats NT, fallback ruolo."""

from __future__ import annotations

from players.models import MatchRoster, PlayerBonus
from players.team_data import (
    card_prob_from_per90,
    default_minutes_for_role,
    get_match_penalty_rate,
    get_penalty_taker,
    get_player_stats,
    is_penalty_taker,
)

# Fallback per ruolo se mancano stats NT
_YELLOW_RATE = {"GK": 0.04, "DEF": 0.20, "MID": 0.16, "FWD": 0.11}
_RED_RATE = {"GK": 0.003, "DEF": 0.012, "MID": 0.010, "FWD": 0.007}
_OWN_GOAL_RATE = {"GK": 0.001, "DEF": 0.006, "MID": 0.003, "FWD": 0.001}

_PEN_MISS = 0.22
_PEN_SAVE = 0.22


def _team_name(roster: MatchRoster, side: str) -> str:
    return roster.home if side == "home" else roster.away


def _estimate_gk_goal_prob(player: PlayerBonus, p_any_goal: float) -> float:
    if not player.is_goalkeeper:
        return 0.0
    return min(p_any_goal, 0.003 + p_any_goal * 0.5)


def _card_probs(player: PlayerBonus, roster: MatchRoster) -> tuple[float, float]:
    """P(yellow), P(red) — stats NT > fallback ruolo. Non sovrascrive valori API."""
    if player.p_yellow is not None and player.p_yellow > 0:
        p_yellow = float(player.p_yellow)
    else:
        team = _team_name(roster, player.side)
        stats = get_player_stats(team, player.name)
        if stats and stats.yellow_per90 > 0:
            minutes = stats.minutes_expected or default_minutes_for_role(player.role)
            p_yellow = card_prob_from_per90(stats.yellow_per90, minutes)
        else:
            p_yellow = _YELLOW_RATE.get(player.role.upper(), 0.12)

    if player.p_red is not None and player.p_red > 0:
        p_red = float(player.p_red)
    else:
        team = _team_name(roster, player.side)
        stats = get_player_stats(team, player.name)
        if stats and stats.red_per90 > 0:
            minutes = stats.minutes_expected or default_minutes_for_role(player.role)
            p_red = card_prob_from_per90(stats.red_per90, minutes)
        else:
            p_red = _RED_RATE.get(player.role.upper(), 0.008)

    return p_yellow, p_red


def _penalty_probs_for_player(
    player: PlayerBonus,
    roster: MatchRoster,
    *,
    p_team_pen: float,
) -> tuple[float, float, float]:
    """
    Return (p_pen_scored, p_pen_missed, p_pen_saved) using rigorista ufficiale.

    p_team_pen = P(la squadra del giocatore batte almeno un rigore in partita).
    """
    team = _team_name(roster, player.side)

    if player.is_goalkeeper:
        # Portiere avversario: rigore subito = rigore guadagnato dall'altra squadra
        p_faced = p_team_pen  # already computed for opposing team below
        p_saved = p_faced * _PEN_SAVE
        return 0.0, 0.0, p_saved

    info = get_penalty_taker(team)
    if not info:
        return 0.0, 0.0, 0.0

    is_primary, is_backup = is_penalty_taker(team, player.name)
    if not is_primary and not is_backup:
        return 0.0, 0.0, 0.0

    share = info.primary_share if is_primary else (1.0 - info.primary_share)
    p_taken = p_team_pen * share
    p_scored = p_taken * info.conversion_rate
    p_missed = p_taken * (1.0 - info.conversion_rate)
    return p_scored, p_missed, 0.0


def attach_event_probs(roster: MatchRoster, match) -> MatchRoster:
    """Fill malus/bonus secondari: rigoristi DB + stats cartellini."""
    match_pen = get_match_penalty_rate()
    p_home_pen = match_pen / 2.0
    p_away_pen = match_pen / 2.0
    team_pen = {"home": p_home_pen, "away": p_away_pen}

    # Portieri: rigore parato = rigore dell'avversario
    opp_pen = {"home": p_away_pen, "away": p_home_pen}

    updated: list[PlayerBonus] = []
    for player in roster.players:
        p_yellow, p_red = _card_probs(player, roster)
        p_own = _OWN_GOAL_RATE.get(player.role.upper(), 0.002)

        if player.is_goalkeeper:
            p_pen_scored, p_pen_missed = 0.0, 0.0
            p_pen_saved = opp_pen[player.side] * _PEN_SAVE
        else:
            p_pen_scored, p_pen_missed, p_pen_saved = _penalty_probs_for_player(
                player, roster, p_team_pen=team_pen[player.side]
            )

        p_any = float(player.p_goal or 0.0)
        p_gk_goal = _estimate_gk_goal_prob(player, p_any)

        updated.append(
            player.with_probs(
                p_yellow=p_yellow,
                p_red=p_red,
                p_own_goal=p_own,
                p_penalty_scored=p_pen_scored,
                p_penalty_missed=p_pen_missed,
                p_penalty_saved=p_pen_saved,
                p_gk_goal=p_gk_goal,
            )
        )

    roster.players = updated
    return roster
