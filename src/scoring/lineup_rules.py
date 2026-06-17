"""Fantamondiale lineup bonus/malus payoffs (regolamento §8.3)."""

from __future__ import annotations

# Bonus fissi
BONUS_PENALTY_SCORED = 3
BONUS_PENALTY_SAVED = 4
BONUS_GK_GOAL = 10
BONUS_DEFENDER_CS = 1

# Malus fissi
MALUS_YELLOW = -1
MALUS_RED = -2
MALUS_OWN_GOAL = -2
MALUS_PENALTY_MISSED = -3

# Vice allenatore (§7.6)
VICE_MIN_BONUS_GOAL = 5
LINEUP_SIZE = 4

# Pronostici evento daily (§8.2 — etichette §7.5)
PAYOFF_FIRST_SUB = 5  # K
PAYOFF_FIRST_CARD = 4  # L
