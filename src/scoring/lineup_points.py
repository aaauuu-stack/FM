"""Fantamondiale lineup scoring and EV per player (regolamento §8.3)."""

from __future__ import annotations

from dataclasses import dataclass, field

from players.models import PlayerBonus
from scoring.lineup_rules import (
    BONUS_DEFENDER_CS,
    BONUS_GK_GOAL,
    BONUS_PENALTY_SAVED,
    BONUS_PENALTY_SCORED,
    MALUS_OWN_GOAL,
    MALUS_PENALTY_MISSED,
    MALUS_RED,
    MALUS_YELLOW,
)


@dataclass
class PlayerEv:
    player: PlayerBonus
    ev_goal_action: float = 0.0
    ev_goal_penalty: float = 0.0
    ev_gk_goal: float = 0.0
    ev_clean_sheet: float = 0.0
    ev_penalty_saved: float = 0.0
    ev_malus: float = 0.0
    ev_total: float = 0.0
    p_goal_action: float = 0.0
    p_clean_sheet: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def ev_goal(self) -> float:
        return self.ev_goal_action + self.ev_goal_penalty + self.ev_gk_goal


def _goal_action_prob(player: PlayerBonus) -> float:
    """P(gol su azione/punizione) — esclude rigori (bonus separato +3)."""
    p_any = float(player.p_goal or 0.0)
    p_pen = float(player.p_penalty_scored or 0.0)
    if player.is_goalkeeper:
        p_gk = float(player.p_gk_goal or 0.0)
        return max(0.0, min(p_any, p_gk if p_gk > 0 else p_any * 0.85))
    return max(0.0, p_any - p_pen)


def compute_player_ev(player: PlayerBonus) -> PlayerEv:
    """Expected FM points from one schierato (bonus + malus §8.3)."""
    p_pen_scored = float(player.p_penalty_scored or 0.0)
    p_pen_saved = float(player.p_penalty_saved or 0.0)
    p_yellow = float(player.p_yellow or 0.0)
    p_red = float(player.p_red or 0.0)
    p_own_goal = float(player.p_own_goal or 0.0)
    p_pen_missed = float(player.p_penalty_missed or 0.0)
    p_cs = float(player.p_clean_sheet or 0.0)

    ev_goal_action = 0.0
    ev_goal_penalty = p_pen_scored * BONUS_PENALTY_SCORED
    ev_gk_goal = 0.0
    ev_clean_sheet = 0.0
    p_goal_action = _goal_action_prob(player)

    if player.is_goalkeeper:
        p_gk_goal = float(player.p_gk_goal or 0.0)
        if p_gk_goal <= 0 and float(player.p_goal or 0.0) > 0:
            p_gk_goal = float(player.p_goal or 0.0)
        ev_gk_goal = p_gk_goal * BONUS_GK_GOAL
        if player.bonus_clean_sheet > 0:
            ev_clean_sheet = p_cs * player.bonus_clean_sheet
    else:
        ev_goal_action = p_goal_action * player.bonus_goal
        if player.is_defender:
            ev_clean_sheet = p_cs * BONUS_DEFENDER_CS

    ev_penalty_saved = p_pen_saved * BONUS_PENALTY_SAVED

    ev_malus = (
        p_yellow * abs(MALUS_YELLOW)
        + p_red * abs(MALUS_RED)
        + p_own_goal * abs(MALUS_OWN_GOAL)
        + p_pen_missed * abs(MALUS_PENALTY_MISSED)
    )

    breakdown = {}
    if ev_goal_action:
        breakdown["gol_azione"] = ev_goal_action
    if ev_goal_penalty:
        breakdown["gol_rigore"] = ev_goal_penalty
    if ev_gk_goal:
        breakdown["gol_portiere"] = ev_gk_goal
    if ev_clean_sheet:
        breakdown["clean_sheet"] = ev_clean_sheet
    if ev_penalty_saved:
        breakdown["rigore_parato"] = ev_penalty_saved
    if ev_malus:
        breakdown["malus"] = -ev_malus

    ev_total = (
        ev_goal_action
        + ev_goal_penalty
        + ev_gk_goal
        + ev_clean_sheet
        + ev_penalty_saved
        - ev_malus
    )

    return PlayerEv(
        player=player,
        ev_goal_action=ev_goal_action,
        ev_goal_penalty=ev_goal_penalty,
        ev_gk_goal=ev_gk_goal,
        ev_clean_sheet=ev_clean_sheet,
        ev_penalty_saved=ev_penalty_saved,
        ev_malus=ev_malus,
        ev_total=ev_total,
        p_goal_action=p_goal_action,
        p_clean_sheet=p_cs,
        breakdown=breakdown,
    )
