"""Load FM player bonus roster from YAML (parsed from screenshots)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from players.models import MatchRoster, PlayerBonus
from scoring.lineup_rules import VICE_MIN_BONUS_GOAL


def _require_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}: {value!r}") from exc


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sì"}


def load_roster(path: str | Path) -> MatchRoster:
    """Load roster YAML exported from FM app screenshots."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Roster YAML must be a mapping")

    home = str(raw.get("home", "")).strip()
    away = str(raw.get("away", "")).strip()
    if not home or not away:
        raise ValueError("Roster must include home and away team names")

    players_raw = raw.get("players")
    if not isinstance(players_raw, list) or not players_raw:
        raise ValueError("Roster must include a non-empty players list")

    vice_name = str(raw.get("vice_allenatore", "")).strip()

    players: list[PlayerBonus] = []
    for idx, item in enumerate(players_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Player entry #{idx} must be a mapping")
        name = str(item.get("name", "")).strip()
        side = str(item.get("side", "")).strip().lower()
        role = str(item.get("role", "")).strip().upper()
        if not name:
            raise ValueError(f"Player entry #{idx} missing name")
        if side not in {"home", "away"}:
            raise ValueError(f"Player {name}: side must be 'home' or 'away'")
        if role not in {"GK", "DEF", "MID", "FWD"}:
            raise ValueError(f"Player {name}: role must be GK, DEF, MID or FWD")

        is_vice = _parse_bool(item.get("vice_allenatore")) or (
            vice_name != "" and name.lower() == vice_name.lower()
        )

        players.append(
            PlayerBonus(
                name=name,
                side=side,
                role=role,
                bonus_goal=_require_int(item.get("bonus_goal", 0), "bonus_goal"),
                bonus_clean_sheet=_require_int(
                    item.get("bonus_clean_sheet", 0), "bonus_clean_sheet"
                ),
                starter=_parse_bool(item.get("starter"), default=False),
                vice_allenatore=is_vice,
            )
        )

    roster = MatchRoster(
        match_id=str(raw.get("match_id", "")).strip() or _default_match_id(home, away),
        home=home,
        away=away,
        kickoff=str(raw.get("kickoff", "")).strip(),
        players=players,
    )

    vice = roster.vice_player()
    if vice and vice.bonus_goal < VICE_MIN_BONUS_GOAL:
        raise ValueError(
            f"Vice allenatore {vice.name}: bonus gol {vice.bonus_goal} "
            f"< minimo {VICE_MIN_BONUS_GOAL} (regolamento §7.6)"
        )

    return roster


def _default_match_id(home: str, away: str) -> str:
    return f"{home[:3].upper()}-{away[:3].upper()}"
