"""National team reference data: penalty takers and player stats."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from odds.api_normalize import normalize_team
from players.name_match import normalize_player, players_match


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class PenaltyTakerInfo:
    primary: str
    backup: str
    conversion_rate: float
    primary_share: float


@dataclass(frozen=True)
class PlayerStatProfile:
    goals_per90: float = 0.0
    yellow_per90: float = 0.0
    red_per90: float = 0.0
    minutes_expected: float = 85.0


@lru_cache(maxsize=1)
def _load_penalty_takers_raw() -> dict[str, Any]:
    path = _data_dir() / "penalty_takers.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def _load_national_stats_raw() -> dict[str, Any]:
    path = _data_dir() / "national_stats.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def team_key(team_name: str) -> str:
    return normalize_team(team_name)


def get_penalty_taker(team_name: str) -> PenaltyTakerInfo | None:
    raw = _load_penalty_takers_raw()
    teams = raw.get("teams") or {}
    entry = teams.get(team_key(team_name))
    if not isinstance(entry, dict):
        return None
    return PenaltyTakerInfo(
        primary=str(entry.get("primary", "")).strip(),
        backup=str(entry.get("backup", "")).strip(),
        conversion_rate=float(entry.get("conversion_rate", 0.78)),
        primary_share=float(entry.get("primary_share", 0.75)),
    )


def get_match_penalty_rate() -> float:
    raw = _load_penalty_takers_raw()
    return float(raw.get("match_penalty_rate", 0.26))


def get_player_stats(team_name: str, player_name: str) -> PlayerStatProfile | None:
    raw = _load_national_stats_raw()
    teams = raw.get("teams") or {}
    team_entry = teams.get(team_key(team_name))
    if not isinstance(team_entry, dict):
        return None
    players = team_entry.get("players") or {}
    if not isinstance(players, dict):
        return None

    target = normalize_player(player_name)
    for name, stats in players.items():
        if normalize_player(str(name)) == target or players_match(player_name, str(name)):
            if not isinstance(stats, dict):
                return None
            return PlayerStatProfile(
                goals_per90=float(stats.get("goals_per90", 0.0)),
                yellow_per90=float(stats.get("yellow_per90", 0.0)),
                red_per90=float(stats.get("red_per90", 0.0)),
                minutes_expected=float(stats.get("minutes_expected", 85.0)),
            )
    return None


def is_penalty_taker(team_name: str, player_name: str) -> tuple[bool, bool]:
    """Return (is_primary, is_backup) for player on team."""
    info = get_penalty_taker(team_name)
    if not info:
        return False, False
    is_primary = players_match(player_name, info.primary)
    is_backup = players_match(player_name, info.backup)
    return is_primary, is_backup


def default_minutes_for_role(role: str) -> float:
    return {"GK": 90.0, "DEF": 88.0, "MID": 85.0, "FWD": 78.0}.get(role.upper(), 85.0)


def card_prob_from_per90(rate_per90: float, minutes: float) -> float:
    """P(at least one event) from Poisson rate."""
    if rate_per90 <= 0 or minutes <= 0:
        return 0.0
    lam = rate_per90 * (minutes / 90.0)
    # 1 - P(0) = 1 - e^-lambda
    import math

    return min(0.65, 1.0 - math.exp(-lam))
