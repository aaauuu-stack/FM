"""Parallel prefetch of independent odds/scrape sources for one match."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from odds.api_client import fetch_odds
from odds.api_normalize import event_to_match_data, find_event
from odds.event_odds_bundle import fetch_combined_event_player_odds
from odds.match_loader import MatchOdds
from odds.merge_providers import merge_match_data, merge_match_data_fill_gaps
from odds.oddspapi_bundle import OddsPapiBundle, fetch_oddspapi_bundle
from odds.oddspapi_client import oddspapi_configured
from odds.sofascore_bundle import SofaScoreBundle, fetch_sofascore_bundle
from players.models import MatchRoster
from predict.timing import timed


def _needs_correct_score(odds: MatchOdds) -> bool:
    return not odds.correct_score or not odds.half_time_correct_score


def _merge_first_card(
    oddspapi: OddsPapiBundle | None,
    sofa: SofaScoreBundle | None,
) -> tuple[dict[str, float], str]:
    probs: dict[str, float] = {}
    notes: list[str] = []
    if oddspapi and oddspapi.first_card_probs:
        probs.update(oddspapi.first_card_probs)
        if oddspapi.first_card_note:
            notes.append(oddspapi.first_card_note)
    if sofa and sofa.first_card_probs:
        for name, p in sofa.first_card_probs.items():
            if name not in probs:
                probs[name] = p
        if sofa.first_card_note:
            notes.append(sofa.first_card_note)
    return probs, (" | ".join(notes) if notes else "")


@dataclass
class MatchPrefetch:
    """Results from parallel network fetches for a single fixture."""

    oddspapi_props: tuple[dict[str, float], dict[str, float], str] | None = None
    sofa_props: tuple | None = None
    goalscorer_probs: dict[str, float] | None = None
    event_player_props: dict[str, dict[str, float]] | None = None
    first_card: tuple[dict[str, float], str] | None = None


def _fetch_sofa_lite(
    roster: MatchRoster,
    kickoff: str,
    oddspapi_bundle: OddsPapiBundle | None,
    match,
    *,
    use_scrape: bool,
) -> SofaScoreBundle | None:
    if not use_scrape:
        return None

    sofa_id = oddspapi_bundle.sofascore_event_id if oddspapi_bundle else None
    if sofa_id is None:
        return None

    need_cs = _needs_correct_score(match.odds)
    op_goals = bool(oddspapi_bundle and oddspapi_bundle.goal_probs)
    op_cards = bool(oddspapi_bundle and oddspapi_bundle.card_probs)
    need_fc = not bool(oddspapi_bundle and oddspapi_bundle.first_card_probs)

    if need_cs or not op_goals or not op_cards or need_fc:
        return fetch_sofascore_bundle(
            roster.home,
            roster.away,
            kickoff,
            event_id=sofa_id,
            need_match_cs=need_cs,
            need_goal_props=not op_goals,
            need_card_props=not op_cards,
            need_first_card=need_fc,
        )
    return None


def build_match_parallel(
    roster: MatchRoster,
    *,
    sport: str,
    region: str,
    refresh: bool,
    use_oddspapi: bool,
    use_scrape: bool,
) -> tuple:
    """
    Fetch The Odds API once, then enrich match + prefetch player/L data in parallel.

    SofaScore lite: 1 HTTP call, solo se OddsPapi espone sofascoreId.

    Returns (match, source_note, requests_remaining, event_id, prefetch).
    """
    with timed("odds_api_listing"):
        fetch_result = fetch_odds(sport=sport, region=region, force_refresh=refresh)
        event = find_event(fetch_result.events, roster.home, roster.away)
        match = event_to_match_data(event)
    kickoff = roster.kickoff or str(event.get("commence_time", ""))
    event_id = str(event.get("id", ""))

    prefetch = MatchPrefetch()
    oddspapi_bundle: OddsPapiBundle | None = None
    sofa_bundle: SofaScoreBundle | None = None

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_event_odds = (
            pool.submit(
                fetch_combined_event_player_odds,
                event_id,
                sport=sport,
                region=region,
                force_refresh=refresh,
            )
            if event_id
            else None
        )

        f_oddspapi = (
            pool.submit(
                fetch_oddspapi_bundle,
                roster.home,
                roster.away,
                kickoff,
                need_match_cs=True,
                need_props=True,
                need_first_card=True,
            )
            if use_oddspapi and oddspapi_configured()
            else None
        )

        if f_oddspapi is not None:
            with timed("oddspapi_bundle"):
                try:
                    oddspapi_bundle = f_oddspapi.result()
                except (RuntimeError, ValueError) as exc:
                    print(f"  [warn] OddsPapi non disponibile: {exc}", file=sys.stderr)

        sources = ["The Odds API"]

        if oddspapi_bundle and oddspapi_bundle.match_odds:
            match = merge_match_data(match, oddspapi_bundle.match_odds)
            sources.append("OddsPapi")
        elif use_oddspapi and not oddspapi_configured():
            print(
                "  [warn] OddsPapi non configurato — vedi docs/API_SETUP.md",
                file=sys.stderr,
            )

        if use_scrape:
            with timed("sofascore_bundle"):
                try:
                    sofa_bundle = _fetch_sofa_lite(
                        roster,
                        kickoff,
                        oddspapi_bundle,
                        match,
                        use_scrape=True,
                    )
                except (RuntimeError, ValueError) as exc:
                    print(f"  [warn] Scraping non disponibile: {exc}", file=sys.stderr)

        if sofa_bundle and sofa_bundle.match_odds:
            match = merge_match_data_fill_gaps(match, sofa_bundle.match_odds)
            if (
                sofa_bundle.match_odds.correct_score
                or sofa_bundle.match_odds.half_time_correct_score
            ):
                sources.append("SofaScore")

        if oddspapi_bundle and oddspapi_bundle.goal_probs is not None:
            prefetch.oddspapi_props = (
                oddspapi_bundle.goal_probs,
                oddspapi_bundle.card_probs or {},
                oddspapi_bundle.props_note,
            )

        if sofa_bundle and sofa_bundle.goal_probs is not None:
            prefetch.sofa_props = (
                sofa_bundle.goal_probs,
                sofa_bundle.card_probs or {},
                {},
                sofa_bundle.props_note,
            )

        if use_oddspapi or use_scrape:
            prefetch.first_card = _merge_first_card(oddspapi_bundle, sofa_bundle)

        if f_event_odds is not None:
            with timed("event_player_odds"):
                try:
                    gs, props = f_event_odds.result()
                    prefetch.goalscorer_probs = gs
                    prefetch.event_player_props = props
                except RuntimeError:
                    pass

    cache_note = "cache" if fetch_result.from_cache else "live"
    source_note = f"{' + '.join(sources)} ({cache_note})"
    return match, source_note, fetch_result.requests_remaining, event_id, prefetch
