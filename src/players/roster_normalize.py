"""Normalize parsed FM roster fields after vision/OCR."""

from __future__ import annotations

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
