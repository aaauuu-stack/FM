"""Tests for roster YAML loader (vice allenatore)."""

from pathlib import Path

import pytest

from players.models import PlayerBonus
from players.roster_loader import load_roster

PLAYERS_DIR = Path(__file__).parent.parent / "data" / "players"


def test_load_eng_cro_roster():
    roster = load_roster(PLAYERS_DIR / "eng-cro.yaml")
    assert roster.home == "England"
    assert len(roster.players) >= 10
    kane = next(p for p in roster.players if p.name == "Kane")
    assert kane.bonus_goal == 3
    assert kane.side == "home"
    sucic = roster.vice_player()
    assert sucic is not None
    assert sucic.name == "Sucic"
    assert sucic.vice_allenatore is True


def test_vice_requires_min_bonus():
    bad = {
        "home": "A",
        "away": "B",
        "players": [
            {
                "name": "Low",
                "side": "home",
                "role": "MID",
                "bonus_goal": 2,
                "vice_allenatore": True,
            },
            {"name": "X", "side": "away", "role": "FWD", "bonus_goal": 8},
            {"name": "Y", "side": "home", "role": "DEF", "bonus_goal": 8},
            {"name": "Z", "side": "away", "role": "MID", "bonus_goal": 8},
            {"name": "W", "side": "home", "role": "FWD", "bonus_goal": 8},
        ],
    }
    import yaml
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.dump(bad, fh)
        path = fh.name

    with pytest.raises(ValueError, match="Vice allenatore"):
        load_roster(path)
