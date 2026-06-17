"""Tests for player name matching and Poisson goal estimates."""

from odds.goalscorer import attach_poisson_goal_estimates
from players.name_match import normalize_player, players_match
from odds.match_loader import MatchData, MatchOdds
from players.models import MatchRoster, PlayerBonus


def _sample_match() -> MatchData:
    return MatchData(
        match_id="TEST",
        home="Home",
        away="Away",
        kickoff="2026-06-15T21:00:00",
        odds=MatchOdds(
            h2h={"home": 1.65, "draw": 3.80, "away": 5.00},
            totals={"line": 2.5, "over": 1.90, "under": 1.95},
        ),
    )


def test_players_match_last_name():
    assert players_match("Kane", "Harry Kane")
    assert players_match("KANE", "Harry Kane")


def test_players_match_fm_initial():
    assert players_match("CHALOBAH T.", "Trevoh Chalobah")


def test_normalize_player_strips_initial():
    assert normalize_player("SUCIC L.") == "sucic"


def test_poisson_goal_estimates_assign_outfield_probs():
    roster = MatchRoster(
        match_id="T",
        home="Home",
        away="Away",
        kickoff="",
        players=[
            PlayerBonus(name="Striker", side="home", role="FWD", bonus_goal=10),
            PlayerBonus(name="Keeper", side="away", role="GK", bonus_goal=10, bonus_clean_sheet=5),
        ],
    )

    updated = attach_poisson_goal_estimates(roster, _sample_match())
    striker = next(p for p in updated.players if p.name == "Striker")
    keeper = next(p for p in updated.players if p.name == "Keeper")
    assert striker.p_goal > 0
    assert keeper.p_goal == 0


def test_attach_event_probs_fills_malus_fields():
    from odds.player_events import attach_event_probs

    roster = MatchRoster(
        match_id="T",
        home="Home",
        away="Away",
        players=[PlayerBonus("Def", "home", "DEF", bonus_goal=8, p_goal=0.05)],
    )
    updated = attach_event_probs(roster, _sample_match())
    player = updated.players[0]
    assert float(player.p_yellow or 0) > 0
    assert float(player.p_own_goal or 0) > 0
