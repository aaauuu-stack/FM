"""Tests for K/L event predictions and vice allenatore lineup."""

from unittest.mock import patch

from odds.scrape_sofascore_subs import TeamSubProfile
from players.models import MatchRoster, PlayerBonus
from odds.match_loader import MatchData, MatchOdds
from predict.event_ev import recommend_first_card, recommend_first_sub
from predict.lineup_ev import optimize_lineup
from scoring.lineup_points import compute_player_ev


def _sample_roster() -> MatchRoster:
    def _p(name, side, role, **kw) -> PlayerBonus:
        return PlayerBonus(name, side, role, starter=not kw.pop("vice", False), **kw)

    return MatchRoster(
        match_id="TEST",
        home="England",
        away="Croatia",
        players=[
            _p("Kane", "home", "FWD", bonus_goal=3, p_goal=0.35),
            _p("Toney", "home", "FWD", bonus_goal=9, p_goal=0.12),
            _p(
                "Pickford",
                "home",
                "GK",
                bonus_goal=10,
                bonus_clean_sheet=4,
                p_goal=0.01,
                p_clean_sheet=0.40,
            ),
            _p(
                "Sucic",
                "away",
                "MID",
                bonus_goal=12,
                p_goal=0.06,
                vice=True,
                vice_allenatore=True,
            ),
            _p(
                "Livakovic",
                "away",
                "GK",
                bonus_goal=10,
                bonus_clean_sheet=5,
                p_goal=0.01,
                p_clean_sheet=0.25,
            ),
            _p("Kramaric", "away", "FWD", bonus_goal=5, p_goal=0.18),
        ],
    )


def test_toney_beats_kane_on_ev_with_bonus():
    roster = _sample_roster()
    kane = compute_player_ev(next(p for p in roster.lineup_pool() if p.name == "Kane"))
    toney = compute_player_ev(next(p for p in roster.lineup_pool() if p.name == "Toney"))
    assert toney.ev_total > kane.ev_total


def test_optimize_lineup_requires_both_sides():
    roster = _sample_roster()
    best, _ = optimize_lineup(roster)
    sides = {p.player.side for p in best.all_players}
    assert sides == {"home", "away"}
    assert len(best.players) == 4
    assert best.vice is not None
    assert best.vice.player.name == "Sucic"


def test_vice_not_in_personal_four():
    roster = _sample_roster()
    best, _ = optimize_lineup(roster)
    personal = {p.player.name for p in best.players}
    assert "Sucic" not in personal


def test_event_recommendations_return_players():
    roster = _sample_roster()
    match = MatchData(
        match_id="TEST",
        home="England",
        away="Croatia",
        kickoff="2026-06-15T21:00:00",
        odds=MatchOdds(
            h2h={"home": 1.65, "draw": 3.80, "away": 5.00},
            totals={"line": 2.5, "over": 1.90, "under": 1.95},
        ),
    )
    with patch("odds.event_kl_model.fetch_team_sub_profile") as mock_sub:
        mock_sub.return_value = TeamSubProfile(sample_matches=0)
        sub = recommend_first_sub(roster, match)
        card = recommend_first_card(roster, match)
    assert sub is not None and sub.event_code == "K"
    assert card is not None and card.event_code == "L"
    assert sub.ev == sub.probability * 5
    assert card.ev == card.probability * 4
