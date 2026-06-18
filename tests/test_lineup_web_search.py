"""Tests for web search lineup fallback."""

from unittest.mock import patch

from players.lineup_web_search import _names_in_corpus, fetch_lineups_web_search
from players.models import MatchRoster, PlayerBonus
from players.starters import infer_starters


def _swiss_xi_roster() -> MatchRoster:
    home = [
        "Kobel",
        "Rodriguez R.",
        "Akanji",
        "Elvedi",
        "Widmer",
        "Freuler",
        "Xhaka",
        "Vargas R.",
        "Embolo",
        "Amdouni",
        "Aebischer",
        "Keller",
        "Ndoye",
    ]
    away = [
        "Vasilj",
        "Dedic",
        "Kolasinac",
        "Demirovic",
        "Lukic",
        "Katic",
        "Muharemovic",
        "Bajraktarevic",
        "Basic",
        "Tahirovic",
        "Memic",
        "Hadzikic",
        "Tabakovic",
    ]
    roles = {
        "Kobel": "GK",
        "Keller": "GK",
        "Vasilj": "GK",
        "Hadzikic": "GK",
        "Embolo": "FWD",
        "Amdouni": "FWD",
        "Tabakovic": "FWD",
        "Memic": "FWD",
        "Ndoye": "MID",
    }
    gk_bonus = {
        "Keller": (5, 6),
        "Kobel": (5, 5),
        "Hadzikic": (7, 7),
        "Vasilj": (6, 6),
    }
    players: list[PlayerBonus] = []
    for name in home:
        bg, bcs = gk_bonus.get(name, (8, 0))
        players.append(
            PlayerBonus(
                name=name,
                side="home",
                role=roles.get(name, "DEF" if "ic" in name or name.endswith("mer") else "MID"),
                bonus_goal=bg,
                bonus_clean_sheet=bcs if name in gk_bonus else 0,
                vice_allenatore=name == "Ndoye",
            )
        )
    for name in away:
        bg, bcs = gk_bonus.get(name, (9, 0))
        players.append(
            PlayerBonus(
                name=name,
                side="away",
                role=roles.get(name, "DEF"),
                bonus_goal=bg,
                bonus_clean_sheet=bcs if name in gk_bonus else 0,
            )
        )
    return MatchRoster("T", "Svizzera", "Bosnia", players=players)


def test_names_in_corpus_matches_roster_players():
    roster = _swiss_xi_roster()
    text = (
        "Probabile formazione Svizzera: Kobel; Rodriguez; Akanji; Elvedi; Widmer; "
        "Freuler; Xhaka; Vargas; Embolo; Aebischer. Bosnia: Vasilj, Dedic, Kolasinac, "
        "Demirovic, Lukic, Katic, Muharemovic, Bajraktarevic, Basic, Tahirovic, Memic."
    )
    home = _names_in_corpus(roster.home_players(), text)
    away = _names_in_corpus(roster.away_players(), text)
    assert "Kobel" in home
    assert "Embolo" in home
    assert "Amdouni" not in home
    assert "Vasilj" in away
    assert len(home) >= 6
    assert len(away) >= 6


def test_infer_starters_uses_web_search_when_sofa_missing():
    roster = _swiss_xi_roster()
    corpus = (
        "Svizzera probabile formazione: Kobel Rodriguez Akanji Elvedi Widmer "
        "Freuler Xhaka Vargas Embolo Aebischer. "
        "Bosnia: Vasilj Dedic Kolasinac Demirovic Lukic Katic Muharemovic "
        "Bajraktarevic Basic Tahirovic Memic."
    )
    with patch("players.lineup_web_search.web_search_enabled", return_value=True):
        with patch("players.lineup_web_search._collect_corpus", return_value=corpus):
            with patch(
                "players.starters.fetch_event_gk_starter_names",
                return_value=({"Kobel", "G. Kobel"}, {"Vasilj"}),
            ):
                updated, note = infer_starters(roster, sofascore_event_id=1)

    starters = {p.name for p in updated.players if p.starter}
    assert "Kobel" in starters
    assert "Embolo" in starters
    assert "Amdouni" not in starters
    assert "Vasilj" in starters
    assert "Tabakovic" not in starters
    assert "ricerca online" in note
    assert "portiere home: Kobel (SofaScore)" in note
