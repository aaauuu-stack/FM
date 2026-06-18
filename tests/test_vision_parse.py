"""Tests for vision-based roster parsing (no API calls)."""

from players.vision_parse import roster_from_vision_data

UZB_COL_VISION = {
    "home": "Uzbekistan",
    "away": "Colombia",
    "players": [
        {"name": "Ergashev", "side": "home", "role": "GK", "bonus_goal": 14, "bonus_clean_sheet": 14, "vice": False},
        {"name": "Montero", "side": "away", "role": "GK", "bonus_goal": 5, "bonus_clean_sheet": 5, "vice": False},
        {"name": "Amanov", "side": "home", "role": "FWD", "bonus_goal": 12, "bonus_clean_sheet": 0, "vice": False},
        {"name": "Suarez L.", "side": "away", "role": "FWD", "bonus_goal": 5, "bonus_clean_sheet": 0, "vice": True},
        {"name": "Abdullaev", "side": "home", "role": "MID", "bonus_goal": 13, "bonus_clean_sheet": 0, "vice": False},
        {"name": "Arias J.", "side": "away", "role": "MID", "bonus_goal": 6, "bonus_clean_sheet": 0, "vice": False},
    ],
}


def test_roster_from_vision_data():
    roster = roster_from_vision_data(UZB_COL_VISION)
    assert roster.home == "Uzbekistan"
    assert roster.away == "Colombia"
    assert len(roster.players) == 6
    vice = roster.vice_player()
    assert vice is not None
    assert "suarez" in vice.name.lower()


def test_roster_from_input_pasted_text():
    from players.screen_parse import roster_from_input

    text = """
    UZBEKISTAN - COLOMBIA
    Portieri
    ERGASHEV +14  MONTERO +5
    Attaccanti
    AMANOV +12    SUAREZ L. +5 ✓
    Centrocampisti
    ABDULLAEV +13 ARIAS J. +6
    """
    roster = roster_from_input(pasted_text=text)
    assert roster.home == "Uzbekistan"
    assert len(roster.lineup_pool()) >= 4
