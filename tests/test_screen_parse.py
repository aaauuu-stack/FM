"""Tests for FM screenshot OCR text parsing (no image/Tesseract required)."""

from players.screen_parse import extract_match_teams, extract_players, roster_from_ocr_text


UZB_COL_SAMPLE = """
Uzbekistan - Colombia
Mondiale 2026

Uzbekistan
Nishanov POR +10 +4
Khusanov DIF +9 +3
Shomurodov ATT +5

Colombia
Ospina POR +10 +5
James CEN +6 ✓
Diaz ATT +4
"""

ENG_CRO_SAMPLE = """
Inghilterra vs Croazia

Inghilterra
Pickford POR +10 +4
Kane ATT +3

Croazia
Modric CEN +6
Sucic CEN +12 vice
"""


def test_extract_match_uzbekistan_colombia():
    home, away = extract_match_teams(UZB_COL_SAMPLE)
    assert home == "Uzbekistan"
    assert away == "Colombia"


def test_extract_match_inghilterra_croazia():
    home, away = extract_match_teams(ENG_CRO_SAMPLE)
    assert home == "Inghilterra"
    assert away == "Croazia"


def test_extract_players_and_vice():
    home, away = extract_match_teams(ENG_CRO_SAMPLE)
    players = extract_players(ENG_CRO_SAMPLE, home, away)
    names = {p.name for p in players}
    assert "Kane" in names
    vice = [p for p in players if p.vice_allenatore]
    assert len(vice) == 1
    assert vice[0].name == "Sucic"


def test_roster_from_ocr_text():
    roster = roster_from_ocr_text(UZB_COL_SAMPLE)
    assert roster.home == "Uzbekistan"
    assert roster.away == "Colombia"
    assert len(roster.players) >= 4
