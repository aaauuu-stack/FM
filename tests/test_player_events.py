"""Tests for penalty assignment and stats-based cards."""

from players.models import MatchRoster, PlayerBonus
from odds.player_events import attach_event_probs
from odds.match_loader import MatchData, MatchOdds


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


def test_kane_gets_penalty_scored_prob():
    roster = MatchRoster(
        match_id="T",
        home="England",
        away="Croatia",
        players=[
            PlayerBonus("Kane", "home", "FWD", bonus_goal=3, p_goal=0.35),
            PlayerBonus("Toney", "home", "FWD", bonus_goal=9, p_goal=0.10),
            PlayerBonus("Modric", "away", "MID", bonus_goal=6, p_goal=0.05),
        ],
    )
    updated = attach_event_probs(roster, _sample_match())
    kane = next(p for p in updated.players if p.name == "Kane")
    toney = next(p for p in updated.players if p.name == "Toney")
    assert float(kane.p_penalty_scored or 0) > float(toney.p_penalty_scored or 0)


def test_rice_higher_card_prob_than_fwd():
    roster = MatchRoster(
        match_id="T",
        home="England",
        away="Croatia",
        players=[
            PlayerBonus("Rice", "home", "MID", bonus_goal=7),
            PlayerBonus("Watkins", "home", "FWD", bonus_goal=6),
        ],
    )
    updated = attach_event_probs(roster, _sample_match())
    rice = next(p for p in updated.players if p.name == "Rice")
    watkins = next(p for p in updated.players if p.name == "Watkins")
    assert float(rice.p_yellow or 0) > float(watkins.p_yellow or 0)
