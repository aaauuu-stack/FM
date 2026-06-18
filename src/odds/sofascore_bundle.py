"""Single SofaScore /odds/1/all fetch — lite mode (OddsPapi event id only)."""

from __future__ import annotations

from dataclasses import dataclass

from odds.match_loader import MatchOdds
from odds.oddspapi_client import oddspapi_configured
from odds.oddspapi_normalize import lookup_oddspapi_fixture
from odds.scrape_sofascore import (
    _extract_ht_markets,
    _extract_ft_markets,
    _sofascore_headers,
)
from odds.scrape_client import fetch_json
from odds.scrape_sofascore_players import (
    extract_card_probs_from_sofa_markets,
    extract_first_card_from_sofa_markets,
    extract_goalscorer_from_sofa_markets,
)


@dataclass
class SofaScoreBundle:
    match_odds: MatchOdds | None = None
    goal_probs: dict[str, float] | None = None
    card_probs: dict[str, float] | None = None
    props_note: str = ""
    first_card_probs: dict[str, float] | None = None
    first_card_note: str = ""
    event_id: int | None = None


def sofascore_id_from_fixture(fixture: dict) -> int | None:
    try:
        raw = (fixture.get("externalProviders") or {}).get("sofascoreId")
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def sofascore_event_id_from_oddspapi(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> int | None:
    """SofaScore event id via OddsPapi fixture only (no calendario SofaScore)."""
    if not oddspapi_configured():
        return None
    try:
        fixture = lookup_oddspapi_fixture(home_query, away_query, kickoff_iso)
        return sofascore_id_from_fixture(fixture)
    except (ValueError, TypeError, RuntimeError):
        return None


def _fetch_odds_markets(event_id: int) -> list:
    odds_url = f"https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all"
    odds_result = fetch_json(
        odds_url,
        cache_name=f"sofascore_odds_{event_id}.json",
        extra_headers=_sofascore_headers(),
    )
    return odds_result.data.get("markets") or []


def fetch_sofascore_match_odds_from_event(event_id: int) -> MatchOdds:
    """Correct score FT/HT from cached odds payload (one HTTP call)."""
    markets = _fetch_odds_markets(event_id)
    if not markets:
        raise ValueError(f"SofaScore senza mercati quote per event {event_id}")
    ft = _extract_ft_markets(markets)
    ht = _extract_ht_markets(markets)
    if not ft and not ht:
        raise ValueError(f"SofaScore senza correct score per event {event_id}")
    return MatchOdds(correct_score=ft, half_time_correct_score=ht)


def fetch_sofascore_bundle(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
    *,
    event_id: int | None = None,
    need_match_cs: bool = False,
    need_goal_props: bool = True,
    need_card_props: bool = True,
    need_first_card: bool = False,
) -> SofaScoreBundle:
    """
    One SofaScore HTTP call when OddsPapi provides sofascoreId.

    No calendario, no metadati evento, no stats NT.
    """
    bundle = SofaScoreBundle()
    resolved_id = event_id or sofascore_event_id_from_oddspapi(
        home_query, away_query, kickoff_iso
    )
    if resolved_id is None:
        bundle.props_note = "SofaScore: sofascoreId assente su OddsPapi"
        return bundle

    if not any((need_match_cs, need_goal_props, need_card_props, need_first_card)):
        bundle.event_id = resolved_id
        bundle.props_note = "SofaScore: nessun dato richiesto"
        return bundle

    bundle.event_id = resolved_id
    markets = _fetch_odds_markets(resolved_id)

    if need_match_cs and markets:
        ft = _extract_ft_markets(markets)
        ht = _extract_ht_markets(markets)
        if ft or ht:
            bundle.match_odds = MatchOdds(correct_score=ft, half_time_correct_score=ht)

    notes: list[str] = []
    if need_goal_props or need_card_props:
        goal_probs = (
            extract_goalscorer_from_sofa_markets(markets) if need_goal_props and markets else {}
        )
        card_probs = (
            extract_card_probs_from_sofa_markets(markets) if need_card_props and markets else {}
        )
        if goal_probs:
            notes.append(f"quote gol {len(goal_probs)}")
        if card_probs:
            notes.append(f"quote cartellini {len(card_probs)}")
        bundle.goal_probs = goal_probs if need_goal_props else {}
        bundle.card_probs = card_probs if need_card_props else {}
        bundle.props_note = (
            "SofaScore lite (" + ", ".join(notes) + ")" if notes else "SofaScore lite: mercati vuoti"
        )

    if need_first_card and markets:
        sofa_fc = extract_first_card_from_sofa_markets(markets)
        if sofa_fc:
            bundle.first_card_probs = sofa_fc
            bundle.first_card_note = f"SofaScore first card ({len(sofa_fc)})"

    return bundle
