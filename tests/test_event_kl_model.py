"""Tests for K/L event probability models."""

from unittest.mock import patch

from odds.event_kl_model import (
    MatchContext,
    _context_sub_multiplier,
    _player_historical_sub_weight,
    estimate_first_card_probs,
    estimate_first_sub_probs,
)
from odds.match_loader import MatchData, MatchOdds
from odds.scrape_sofascore_subs import TeamSubProfile
from players.models import MatchRoster, PlayerBonus


def _sample_match() -> MatchData:
    return MatchData(
        match_id="TEST",
        home="England",
        away="Croatia",
        kickoff="2026-06-15T21:00:00",
        odds=MatchOdds(
            h2h={"home": 1.65, "draw": 3.80, "away": 5.00},
            totals={"line": 2.5, "over": 1.90, "under": 1.95},
        ),
    )


def _sample_roster() -> MatchRoster:
    return MatchRoster(
        match_id="T",
        home="England",
        away="Croatia",
        players=[
            PlayerBonus("Toney", "home", "FWD", bonus_goal=9, starter=True, p_goal=0.12),
            PlayerBonus("Rice", "home", "MID", bonus_goal=7, starter=True, p_yellow=0.22),
            PlayerBonus("Kramaric", "away", "FWD", bonus_goal=5, starter=True, p_goal=0.18),
            PlayerBonus("Modric", "away", "MID", bonus_goal=6, starter=True, p_yellow=0.19),
        ],
    )


def test_historical_sub_weight_prefers_player_rate():
    player = PlayerBonus("Toney", "home", "FWD", bonus_goal=9)
    profile = TeamSubProfile(
        player_first_sub_rate={"Toney": 0.4},
        role_first_sub_rate={"FWD": 0.15},
        sample_matches=5,
    )
    w = _player_historical_sub_weight(player, profile)
    assert w > 0.25


def test_underdog_fwd_gets_higher_context_multiplier():
    ctx = MatchContext(
        p_home_win=0.25,
        p_draw=0.25,
        p_away_win=0.50,
        lambda_home=1.0,
        lambda_away=1.5,
        expected_total=2.5,
    )
    fwd = PlayerBonus("Toney", "home", "FWD", bonus_goal=9)
    defn = PlayerBonus("Stones", "home", "DEF", bonus_goal=8)
    assert _context_sub_multiplier(fwd, ctx) > _context_sub_multiplier(defn, ctx)


def test_first_sub_uses_history_and_context():
    roster = _sample_roster()
    home_profile = TeamSubProfile(
        player_first_sub_rate={"Toney": 0.35},
        role_first_sub_rate={"FWD": 0.2},
        sample_matches=4,
    )
    away_profile = TeamSubProfile(sample_matches=0, role_first_sub_rate={"FWD": 0.1})

    with patch(
        "odds.event_kl_model.fetch_team_sub_profile",
        side_effect=[home_profile, away_profile],
    ):
        probs, note = estimate_first_sub_probs(roster, _sample_match())

    assert probs["Toney"] > probs.get("Rice", 0)
    assert "England" in note or "K:" in note


def test_first_card_uses_book_odds_when_available():
    roster = _sample_roster()
    with patch(
        "odds.event_kl_model.fetch_first_card_bookmaker_probs",
        return_value=({"Luka Modric": 0.25}, "OddsPapi first card (1)"),
    ):
        probs, note = estimate_first_card_probs(roster, _sample_match())

    assert probs["Modric"] > probs.get("Rice", 0)
    assert "first card" in note
