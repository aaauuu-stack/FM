"""Tests for full FM lineup scoring (regolamento §8.3)."""

from players.models import PlayerBonus
from scoring.lineup_points import compute_player_ev
from scoring.lineup_rules import (
    BONUS_GK_GOAL,
    BONUS_PENALTY_SCORED,
    MALUS_YELLOW,
)


def test_malus_yellow_reduces_ev():
    clean = PlayerBonus("A", "home", "MID", bonus_goal=8, p_goal=0.2)
    carded = PlayerBonus("B", "home", "MID", bonus_goal=8, p_goal=0.2, p_yellow=0.25)
    assert compute_player_ev(clean).ev_total > compute_player_ev(carded).ev_total
    assert compute_player_ev(carded).ev_malus == 0.25 * abs(MALUS_YELLOW)


def test_penalty_goal_uses_fixed_bonus():
    player = PlayerBonus(
        "Kane",
        "home",
        "FWD",
        bonus_goal=3,
        p_goal=0.0,
        p_penalty_scored=0.5,
    )
    ev = compute_player_ev(player)
    assert ev.ev_goal_penalty == 0.5 * BONUS_PENALTY_SCORED
    assert ev.ev_goal_action == 0.0


def test_gk_goal_uses_fixed_ten_points():
    gk = PlayerBonus(
        "Pickford",
        "home",
        "GK",
        bonus_goal=10,
        bonus_clean_sheet=4,
        p_gk_goal=0.01,
    )
    ev = compute_player_ev(gk)
    assert ev.ev_gk_goal == 0.01 * BONUS_GK_GOAL
