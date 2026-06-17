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


def recommend_first_sub(roster: MatchRoster, match) -> EventRecommendation | None:
    probs, note = estimate_first_sub_probs(roster, match)
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


def recommend_first_card(roster: MatchRoster, match) -> EventRecommendation | None:
    probs, note = estimate_first_card_probs(roster, match)
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


def rank_event_alternatives(
    roster: MatchRoster,
    match,
    event_code: str,
    top_n: int = 3,
) -> list[EventRecommendation]:
    if event_code == "K":
        probs, label = estimate_first_sub_probs(roster, match)
        payoff = PAYOFF_FIRST_SUB
        event_label = "Primo sostituito"
    elif event_code == "L":
        probs, label = estimate_first_card_probs(roster, match)
        payoff = PAYOFF_FIRST_CARD
        event_label = "Primo ammonito"
    else:
        return []

    ranked = sorted(probs.items(), key=lambda item: item[1], reverse=True)
    return [
        EventRecommendation(
            event_code=event_code,
            event_label=event_label,
            player_name=name,
            probability=p,
            payoff_pts=payoff,
            ev=p * payoff,
            source_note=label,
        )
        for name, p in ranked[:top_n]
    ]
