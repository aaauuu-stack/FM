"""Normalize parsed FM roster fields after vision/OCR."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from players.models import PlayerBonus


def finalize_goalkeeper_bonuses(players: list[PlayerBonus]) -> list[PlayerBonus]:
    """
    Vision/OCR sometimes omits bonus_clean_sheet for away GKs.

    FM shows two +N for portieri (gol + porta inviolata). If only one was read,
    copy bonus_goal into bonus_clean_sheet so clean-sheet EV is not zero.
    """
    updated: list[PlayerBonus] = []
    for player in players:
        if player.is_goalkeeper and player.bonus_clean_sheet <= 0 and player.bonus_goal > 0:
            updated.append(
                replace(player, bonus_clean_sheet=player.bonus_goal)
            )
        else:
            updated.append(player)
    return updated


def harmonize_goalkeeper_bonuses(players: list[PlayerBonus]) -> list[PlayerBonus]:
    """
    Fix cross-column parse bleed (e.g. home Keller +5 picks away +6 for CS).

    NT squads usually share the same GK bonus pair; outliers matching the
    majority goal but wrong CS are corrected.
    """
    updated = list(players)
    for side in ("home", "away"):
        gks = [p for p in updated if p.is_goalkeeper and p.side == side]
        if len(gks) < 2:
            continue
        pair_counts = Counter((p.bonus_goal, p.bonus_clean_sheet) for p in gks)
        (mode_goal, mode_cs), mode_n = pair_counts.most_common(1)[0]
        if mode_n < 2:
            continue
        for i, player in enumerate(updated):
            if not player.is_goalkeeper or player.side != side:
                continue
            if (player.bonus_goal, player.bonus_clean_sheet) == (mode_goal, mode_cs):
                continue
            if player.bonus_goal == mode_goal and player.bonus_clean_sheet != mode_cs:
                updated[i] = replace(player, bonus_clean_sheet=mode_cs)
    return updated


def normalize_parsed_roster(players: list[PlayerBonus]) -> list[PlayerBonus]:
    """Post-process GK bonuses after vision/OCR."""
    players = finalize_goalkeeper_bonuses(players)
    return harmonize_goalkeeper_bonuses(players)
