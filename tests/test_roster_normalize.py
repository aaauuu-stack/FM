"""Tests for post-parse GK bonus normalization."""

from players.models import PlayerBonus
from players.roster_normalize import harmonize_goalkeeper_bonuses, normalize_parsed_roster
from players.screen_parse import extract_match_teams, extract_players


def test_harmonize_gk_cross_column_bleed():
    players = [
        PlayerBonus("Keller", "home", "GK", bonus_goal=5, bonus_clean_sheet=6),
        PlayerBonus("Kobel", "home", "GK", bonus_goal=5, bonus_clean_sheet=5),
        PlayerBonus("Mvogo", "home", "GK", bonus_goal=5, bonus_clean_sheet=5),
        PlayerBonus("Hadzikic", "away", "GK", bonus_goal=6, bonus_clean_sheet=6),
        PlayerBonus("Vasilj", "away", "GK", bonus_goal=6, bonus_clean_sheet=6),
    ]
    fixed = harmonize_goalkeeper_bonuses(players)
    keller = next(p for p in fixed if p.name == "Keller")
    assert keller.bonus_goal == 5
    assert keller.bonus_clean_sheet == 5


def test_gk_ocr_does_not_steal_away_cs_bonus():
    text = """
SVIZZERA - BOSNIA
Portieri
KELLER +5  HADZIKIC +6 +6
KOBEL +5 +5  VASILJ +6 +6
Attaccanti
EMBOLO +5  TABAKOVIC +12
DEDIC +8   BASIC +9
Centrocampisti
NDOYE +6   LUKIC +8
XHAKA +8   KATIC +9
"""
    home, away = extract_match_teams(text)
    players = extract_players(text, home, away)
    keller = next(p for p in players if "keller" in p.name.lower())
    hadzikic = next(p for p in players if "hadzikic" in p.name.lower())
    assert keller.bonus_goal == 5
    assert keller.bonus_clean_sheet == 5
    assert hadzikic.bonus_goal == 6
    assert hadzikic.bonus_clean_sheet == 6


def test_normalize_parsed_roster_fills_then_harmonizes():
    players = normalize_parsed_roster(
        [PlayerBonus("Hadzikic", "away", "GK", bonus_goal=6, bonus_clean_sheet=0)]
    )
    assert players[0].bonus_clean_sheet == 6
