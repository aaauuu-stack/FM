"""Tests for player name matching and Poisson goal estimates."""

from odds.goalscorer import attach_poisson_goal_estimates
from scoring.lineup_points import compute_player_ev
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
    assert float(keeper.p_goal or 0) == 0


def test_poisson_fills_only_missing_goal_probs():
    """Se un attaccante ha già P(gol) da book, Poisson riempie solo gli altri."""
    from odds.goalscorer import attach_goal_probs

    roster = MatchRoster(
        match_id="T",
        home="Home",
        away="Away",
        kickoff="",
        players=[
            PlayerBonus(name="Striker", side="home", role="FWD", bonus_goal=5, p_goal=0.25),
            PlayerBonus(name="Backup", side="home", role="FWD", bonus_goal=12),
            PlayerBonus(name="Def", side="away", role="DEF", bonus_goal=10),
        ],
    )
    roster, note = attach_goal_probs(
        roster,
        _sample_match(),
        sport="soccer_fifa_world_cup",
        region="eu",
        goalscorer_probs={},
        event_player_props={"goal": {}, "card": {}, "red": {}},
    )
    striker = next(p for p in roster.players if p.name == "Striker")
    backup = next(p for p in roster.players if p.name == "Backup")
    defender = next(p for p in roster.players if p.name == "Def")
    assert striker.p_goal == 0.25
    assert float(backup.p_goal or 0) > 0
    assert float(defender.p_goal or 0) > 0
    assert "Poisson" in note


def test_poisson_low_bonus_fwd_gets_higher_p_goal():
    """Bonus FM basso → peso Poisson più alto (titolare probabile)."""
    roster = MatchRoster(
        match_id="T",
        home="Home",
        away="Away",
        players=[
            PlayerBonus(name="Starter", side="home", role="FWD", bonus_goal=5),
            PlayerBonus(name="Backup", side="home", role="FWD", bonus_goal=12),
        ],
    )
    updated = attach_poisson_goal_estimates(roster, _sample_match())
    starter = next(p for p in updated.players if p.name == "Starter")
    backup = next(p for p in updated.players if p.name == "Backup")
    assert float(starter.p_goal or 0) > float(backup.p_goal or 0)


def test_gk_clean_sheet_when_bonus_cs_missing():
    """Hadzikic-style: vision puts +6 only in bonus_goal — CS EV must still count."""
    from scoring.lineup_rules import gk_clean_sheet_bonus

    gk = PlayerBonus(
        "Hadzikic",
        "away",
        "GK",
        bonus_goal=6,
        bonus_clean_sheet=0,
        starter=True,
        p_clean_sheet=0.14,
    )
    assert gk_clean_sheet_bonus(gk) == 6
    ev = compute_player_ev(gk)
    assert ev.ev_clean_sheet > 0
    assert "clean_sheet" in ev.breakdown


def test_finalize_goalkeeper_bonuses():
    from players.roster_normalize import finalize_goalkeeper_bonuses

    players = finalize_goalkeeper_bonuses(
        [PlayerBonus("Hadzikic", "away", "GK", bonus_goal=6, bonus_clean_sheet=0)]
    )
    assert players[0].bonus_clean_sheet == 6


def test_goalscorer_no_match_preserves_existing_p_goal():
    from odds.goalscorer import apply_goalscorer_probs

    roster = MatchRoster(
        "T",
        "Home",
        "Away",
        players=[
            PlayerBonus("Striker", "home", "FWD", p_goal=0.25),
            PlayerBonus("Other", "home", "FWD", p_goal=0.0),
        ],
    )
    probs = {"Unknown Player": 0.40}
    updated, note = apply_goalscorer_probs(roster, probs)
    striker = next(p for p in updated.players if p.name == "Striker")
    assert striker.p_goal == 0.25


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
