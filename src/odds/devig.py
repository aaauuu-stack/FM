"""Remove bookmaker margin from implied probabilities."""

from __future__ import annotations


def proportional_devig(odds: dict[str, float]) -> dict[str, float]:
    """
    Convert decimal odds to fair probabilities via proportional de-vig.

    Use only for mutually exclusive outcomes (1X2, first goalscorer, first card).
    Each probability is normalized so they sum to 1.
    """
    if not odds:
        raise ValueError("Odds dictionary cannot be empty")

    implied: dict[str, float] = {}
    for key, price in odds.items():
        if price <= 1.0:
            raise ValueError(f"Invalid decimal odds for '{key}': {price} (must be > 1.0)")
        implied[key] = 1.0 / price

    total = sum(implied.values())
    if total <= 0:
        raise ValueError("Sum of implied probabilities must be positive")

    return {key: value / total for key, value in implied.items()}


def independent_implied_probs(odds: dict[str, float]) -> dict[str, float]:
    """
    Implied P(yes) from decimal odds for independent per-player markets.

    Anytime goalscorer and player-to-be-carded: many players can hit in one match,
    so probabilities must NOT be renormalized across the whole market.
    """
    if not odds:
        raise ValueError("Odds dictionary cannot be empty")

    probs: dict[str, float] = {}
    for key, price in odds.items():
        if price <= 1.0:
            raise ValueError(f"Invalid decimal odds for '{key}': {price} (must be > 1.0)")
        probs[key] = 1.0 / price
    return probs


def devig_two_way(over: float, under: float) -> tuple[float, float]:
    """De-vig a two-way market (e.g. Over/Under)."""
    probs = proportional_devig({"over": over, "under": under})
    return probs["over"], probs["under"]
