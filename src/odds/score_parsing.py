"""Shared parsing for correct-score outcome labels."""

from __future__ import annotations

import re

_SCORE_RE = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")


def parse_score_outcome(name: str) -> tuple[int, int] | None:
    """Parse '1-0', '2 - 1', '1:0' into (home, away) goals."""
    if not name:
        return None
    lowered = name.lower()
    if "other" in lowered or "any" in lowered:
        return None
    match = _SCORE_RE.match(name.strip())
    if not match:
        return None
    home, away = int(match.group(1)), int(match.group(2))
    if home > 9 or away > 9:
        return None
    return home, away


def score_key(home: int, away: int) -> str:
    return f"{home}-{away}"
