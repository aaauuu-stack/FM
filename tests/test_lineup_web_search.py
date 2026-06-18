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
    players: list[PlayerBonus] = []
    for name in home:
        players.append(
            PlayerBonus(
                name=name,
                side="home",
                role=roles.get(name, "DEF" if "ic" in name or name.endswith("mer") else "MID"),
                bonus_goal=8,
                vice_allenatore=name == "Ndoye",
            )
        )
    for name in away:
        players.append(
            PlayerBonus(
                name=name,
                side="away",
                role=roles.get(name, "DEF"),
                bonus_goal=9,
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
            updated, note = infer_starters(roster)

    starters = {p.name for p in updated.players if p.starter}
    assert "Kobel" in starters
    assert "Embolo" in starters
    assert "Amdouni" not in starters
    assert "Vasilj" in starters
    assert "Tabakovic" not in starters
    assert "ricerca online" in note
