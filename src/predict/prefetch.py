"""Parallel prefetch of independent odds/scrape sources for one match."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from odds.api_client import fetch_odds
from odds.api_normalize import event_to_match_data, find_event
from odds.event_odds_bundle import fetch_combined_event_player_odds
from odds.match_loader import MatchOdds
from odds.merge_providers import merge_match_data, merge_match_data_fill_gaps
from odds.oddspapi_bundle import OddsPapiBundle, fetch_oddspapi_bundle
from odds.oddspapi_client import oddspapi_configured
from odds.sofascore_bundle import SofaScoreBundle, fetch_sofascore_bundle
from odds.scrape_sofascore_subs import TeamSubProfile, fetch_team_sub_profile
from players.models import MatchRoster


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

    sub_profiles: dict[str, TeamSubProfile] = field(default_factory=dict)
    oddspapi_props: tuple[dict[str, float], dict[str, float], str] | None = None
    sofa_props: tuple | None = None
    goalscorer_probs: dict[str, float] | None = None
    event_player_props: dict[str, dict[str, float]] | None = None
    first_card: tuple[dict[str, float], str] | None = None


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
    Fetch The Odds API once, then enrich match + prefetch player/K/L data in parallel.

    Returns (match, source_note, requests_remaining, event_id, prefetch).
    """
    fetch_result = fetch_odds(sport=sport, region=region, force_refresh=refresh)
    event = find_event(fetch_result.events, roster.home, roster.away)
    match = event_to_match_data(event)
    kickoff = roster.kickoff or str(event.get("commence_time", ""))
    event_id = str(event.get("id", ""))

    need_scrape_match = use_scrape and _needs_correct_score(match.odds)
    prefetch = MatchPrefetch()
    oddspapi_bundle: OddsPapiBundle | None = None
    sofa_bundle: SofaScoreBundle | None = None

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures: dict[str, object] = {}

        if use_oddspapi and oddspapi_configured():
            futures["oddspapi"] = pool.submit(
                fetch_oddspapi_bundle,
                roster.home,
                roster.away,
                kickoff,
                need_match_cs=True,
                need_props=True,
                need_first_card=True,
            )

        if use_scrape:
            futures["sofa"] = pool.submit(
                fetch_sofascore_bundle,
                roster.home,
                roster.away,
                kickoff,
                need_match_cs=need_scrape_match,
                need_props=True,
                need_first_card=True,
            )

        futures["sub_home"] = pool.submit(
            fetch_team_sub_profile,
            roster.home,
            kickoff,
            opponent=roster.away,
        )
        futures["sub_away"] = pool.submit(
            fetch_team_sub_profile,
            roster.away,
            kickoff,
            opponent=roster.home,
        )

        if event_id:
            futures["event_odds"] = pool.submit(
                fetch_combined_event_player_odds,
                event_id,
                sport=sport,
                region=region,
                force_refresh=refresh,
            )

        sources = ["The Odds API"]

        for key, future in futures.items():
            if key in {"sub_home", "sub_away", "event_odds"}:
                continue
            try:
                result = future.result()
            except (RuntimeError, ValueError) as exc:
                if key == "oddspapi":
                    print(f"  [warn] OddsPapi non disponibile: {exc}", file=sys.stderr)
                elif key == "sofa":
                    print(f"  [warn] Scraping non disponibile: {exc}", file=sys.stderr)
                continue

            if key == "oddspapi":
                oddspapi_bundle = result
                if oddspapi_bundle.match_odds:
                    match = merge_match_data(match, oddspapi_bundle.match_odds)
                    sources.append("OddsPapi")
            elif key == "sofa":
                sofa_bundle = result
                if need_scrape_match and sofa_bundle.match_odds:
                    match = merge_match_data_fill_gaps(match, sofa_bundle.match_odds)
                    if sofa_bundle.match_odds.correct_score or sofa_bundle.match_odds.half_time_correct_score:
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
                sofa_bundle.stats or {},
                sofa_bundle.props_note,
            )

        prefetch.sub_profiles = {
            "home": futures["sub_home"].result(),
            "away": futures["sub_away"].result(),
        }

        if use_oddspapi or use_scrape:
            prefetch.first_card = _merge_first_card(oddspapi_bundle, sofa_bundle)

        if "event_odds" in futures:
            try:
                gs, props = futures["event_odds"].result()
                prefetch.goalscorer_probs = gs
                prefetch.event_player_props = props
            except RuntimeError:
                pass

    cache_note = "cache" if fetch_result.from_cache else "live"
    source_note = f"{' + '.join(sources)} ({cache_note})"
    return match, source_note, fetch_result.requests_remaining, event_id, prefetch
