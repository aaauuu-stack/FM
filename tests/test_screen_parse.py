"""Tests for FM screenshot OCR text parsing (no image/Tesseract required)."""

from players.screen_parse import extract_match_teams, extract_players, roster_from_ocr_text

# Realistic OCR from FM app (Uzbekistan – Colombia screen)
UZB_COL_FM = """
SCELTA CALCIATORI
UZBEKISTAN - COLOMBIA

Portieri
bonus porta inviolata
ERGASHEV +14  MONTERO +5
NEMATOV +14   OSPINA +5
YUSUPOV +14   VARGAS C. +5

Calciatori di movimento
Attaccanti
bonus gol fatto
AMANOV +12    CORDOBA JH. +10
KHAMDAMOV +13 DIAZ L. +4
SERGEEV +12   HERNANDEZ C. +8
SHOMURODOV +10 SUAREZ L. +5 ✓

Centrocampisti
ABDULLAEV +13 ARIAS J. +6
ESANOV +13    CAMPAZ +9
"""

ENG_CRO_SAMPLE = """
Inghilterra vs Croazia

Portieri
Pickford +10 +4
Livakovic +10 +5

Attaccanti
Kane +3
Kramaric +5

Centrocampisti
Modric +6
Sucic +12 vice
"""


def test_extract_match_uzbekistan_colombia_banner():
    home, away = extract_match_teams(UZB_COL_FM)
    assert home == "Uzbekistan"
    assert away == "Colombia"


def test_extract_match_uppercase_banner():
    home, away = extract_match_teams("SCELTA\nUZBEKISTAN – COLOMBIA\nPortieri")
    assert home == "Uzbekistan"
    assert away == "Colombia"


def test_extract_players_fm_layout():
    home, away = extract_match_teams(UZB_COL_FM)
    players = extract_players(UZB_COL_FM, home, away)
    names = {(p.name, p.side, p.role) for p in players}
    assert ("Ergashev", "home", "GK") in names or ("ERGASHEV", "home", "GK") in names
    assert ("Montero", "away", "GK") in names or ("MONTERO", "away", "GK") in names
    assert ("Shomurodov", "home", "FWD") in names or ("SHOMURODOV", "home", "FWD") in names
    vice = [p for p in players if p.vice_allenatore]
    assert len(vice) == 1
    assert "suarez" in vice[0].name.lower()


def test_roster_from_fm_ocr():
    roster = roster_from_ocr_text(UZB_COL_FM)
    assert roster.home == "Uzbekistan"
    assert roster.away == "Colombia"
    assert len(roster.players) >= 8


def test_extract_players_column_markers():
    text = """
UZBEKISTAN - COLOMBIA
Portieri
__HOME_COL__
ERGASHEV +14
NEMATOV +14
YUSUPOV +14
__AWAY_COL__
MONTERO +5
OSPINA +5
VARGAS C. +5
Attaccanti
__HOME_COL__
SHOMURODOV +10
__AWAY_COL__
SUAREZ L. +5 ✓
Centrocampisti
__HOME_COL__
ABDULLAEV +13
ESANOV +13
__AWAY_COL__
ARIAS J. +6
CAMPAZ +9
"""
    home, away = extract_match_teams(text)
    players = extract_players(text, home, away)
    assert sum(1 for p in players if p.side == "home") >= 2
    assert sum(1 for p in players if p.side == "away") >= 2
    assert any(p.vice_allenatore and "suarez" in p.name.lower() for p in players)


def test_balance_when_all_home():
    text = """
UZBEKISTAN - COLOMBIA
Portieri
ERGASHEV +14
NEMATOV +14
MONTERO +5
OSPINA +5
Attaccanti
AMANOV +12
CORDOBA JH. +10
KHAMDAMOV +13
DIAZ L. +4
Centrocampisti
ABDULLAEV +13
ARIAS J. +6
ESANOV +13
CAMPAZ +9
"""
    home, away = extract_match_teams(text)
    players = extract_players(text, home, away)
    assert sum(1 for p in players if p.side == "home") >= 2
    assert sum(1 for p in players if p.side == "away") >= 2


def test_detect_banner_box_finds_bright_horizontal_band():
    from PIL import Image

    from players.screen_parse import _detect_banner_box

    img = Image.new("L", (400, 800), color=20)
    for y in range(96, 144):
        for x in range(400):
            img.putpixel((x, y), 235)
    _, top, _, bottom = _detect_banner_box(img)
    assert 90 <= top <= 100
    assert 140 <= bottom <= 150


def test_extract_match_without_dash_separator():
    home, away = extract_match_teams("SCELTA CALCIATORI\nUZBEKISTAN COLOMBIA\nPortieri")
    assert home == "Uzbekistan"
    assert away == "Colombia"


def test_extract_match_inghilterra_croazia():
    home, away = extract_match_teams(ENG_CRO_SAMPLE)
    assert home == "Inghilterra"
    assert away == "Croazia"
