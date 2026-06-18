"""Daily event predictions K (primo sub) and L (primo ammonito) — regolamento §7.5 / §8.2."""

from __future__ import annotations

from dataclasses import dataclass

from odds.event_kl_model import estimate_first_card_probs, estimate_first_sub_probs
from players.models import MatchRoster
from scoring.lineup_rules import PAYOFF_FIRST_CARD, PAYOFF_FIRST_SUB


@dataclass
class EventRecommendation:
    event_code: str  # "K" or "L"
    event_label: str
    player_name: str
    probability: float
    payoff_pts: int
    ev: float
    source_note: str = ""


def recommend_first_sub(
    roster: MatchRoster,
    match,
    *,
    sub_profiles: dict | None = None,
) -> EventRecommendation | None:
    probs, note = estimate_first_sub_probs(roster, match, sub_profiles=sub_profiles)
    if not probs:
        return None
    best_name = max(probs, key=probs.get)
    p = probs[best_name]
    return EventRecommendation(
        event_code="K",
        event_label="Primo sostituito",
        player_name=best_name,
        probability=p,
        payoff_pts=PAYOFF_FIRST_SUB,
        ev=p * PAYOFF_FIRST_SUB,
        source_note=note,
    )


def recommend_first_card(
    roster: MatchRoster,
    match,
    *,
    book_probs: dict[str, float] | None = None,
    book_note: str = "",
) -> EventRecommendation | None:
    probs, note = estimate_first_card_probs(
        roster,
        match,
        book_probs=book_probs,
        book_note=book_note,
    )
    if not probs:
        return None
    best_name = max(probs, key=probs.get)
    p = probs[best_name]
    return EventRecommendation(
        event_code="L",
        event_label="Primo ammonito",
        player_name=best_name,
        probability=p,
        payoff_pts=PAYOFF_FIRST_CARD,
        ev=p * PAYOFF_FIRST_CARD,
        source_note=note,
    )
