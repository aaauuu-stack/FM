"""Load match YAML files with bookmaker odds."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MatchOdds:
    h2h: dict[str, float] = field(default_factory=dict)
    totals: dict[str, float] = field(default_factory=dict)
    correct_score: dict[str, float] = field(default_factory=dict)
    half_time_correct_score: dict[str, float] = field(default_factory=dict)
    ht_ft: dict[str, float] = field(default_factory=dict)
    ht_result: dict[str, float] = field(default_factory=dict)


@dataclass
class MatchData:
    match_id: str
    home: str
    away: str
    kickoff: str
    odds: MatchOdds


def _parse_score_key(key: str) -> tuple[int, int]:
    parts = str(key).strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid score key '{key}', expected format 'H-A'")
    return int(parts[0]), int(parts[1])


def _validate_odds(odds_raw: dict[str, Any]) -> MatchOdds:
    odds = MatchOdds()

    if "h2h" in odds_raw:
        odds.h2h = {k: float(v) for k, v in odds_raw["h2h"].items()}

    if "totals" in odds_raw:
        odds.totals = {k: float(v) for k, v in odds_raw["totals"].items()}
        if "line" not in odds.totals:
            raise ValueError("totals must include 'line' (e.g. 2.5)")

    if "correct_score" in odds_raw:
        odds.correct_score = {str(k): float(v) for k, v in odds_raw["correct_score"].items()}
        for key in odds.correct_score:
            h, a = _parse_score_key(key)
            if h > 9 or a > 9:
                raise ValueError(f"Correct score '{key}' exceeds app limit of 9 goals per team")

    if "ht_ft" in odds_raw:
        odds.ht_ft = {str(k): float(v) for k, v in odds_raw["ht_ft"].items()}

    if "ht_result" in odds_raw:
        odds.ht_result = {k: float(v) for k, v in odds_raw["ht_result"].items()}

    if "half_time_correct_score" in odds_raw:
        odds.half_time_correct_score = {
            str(k): float(v) for k, v in odds_raw["half_time_correct_score"].items()
        }

    if not odds.h2h and not odds.correct_score and not odds.ht_ft:
        raise ValueError("At least one of h2h, correct_score, or ht_ft odds is required")

    return odds


def load_match(path: str | Path) -> MatchData:
    """Load and validate a match YAML file."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Match file not found: {file_path}")

    with file_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError("Match file must contain a YAML mapping")

    for required in ("match_id", "home", "away", "kickoff", "odds"):
        if required not in raw:
            raise ValueError(f"Missing required field: {required}")

    return MatchData(
        match_id=str(raw["match_id"]),
        home=str(raw["home"]),
        away=str(raw["away"]),
        kickoff=str(raw["kickoff"]),
        odds=_validate_odds(raw["odds"]),
    )
