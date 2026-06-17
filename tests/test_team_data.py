"""Tests for penalty takers DB and national stats."""

from players.team_data import (
    card_prob_from_per90,
    get_penalty_taker,
    get_player_stats,
    is_penalty_taker,
)


def test_england_penalty_taker_is_kane():
    info = get_penalty_taker("England")
    assert info is not None
    assert info.primary == "Kane"
    is_primary, _ = is_penalty_taker("England", "Harry Kane")
    assert is_primary


def test_kane_stats_loaded():
    stats = get_player_stats("England", "Kane")
    assert stats is not None
    assert stats.goals_per90 > 0.4
    assert stats.yellow_per90 > 0


def test_card_prob_from_per90():
    p = card_prob_from_per90(0.20, 90)
    assert 0.15 < p < 0.25
