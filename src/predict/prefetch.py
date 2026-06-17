"""Parallel prefetch of independent odds/scrape sources for one match."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from odds.api_client import fetch_odds
from odds.api_normalize import event_to_match_data, find_event
from odds.match_loader import MatchOdds
from odds.merge_providers import merge_match_data, merge_match_data_fill_gaps
from odds.oddspapi_client import oddspapi_configured
from odds.oddspapi_normalize import fetch_oddspapi_match_odds
from odds.oddspapi_player_props import fetch_oddspapi_player_props
from odds.scrape_normalize import fetch_scraped_match_odds
from odds.scrape_sofascore_players import fetch_sofascore_player_props
from odds.scrape_sofascore_subs import TeamSubProfile, fetch_team_sub_profile
from players.models import MatchRoster


def _needs_correct_score(odds: MatchOdds) -> bool:
    return not odds.correct_score or not odds.half_time_correct_score


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
    from odds.event_kl_model import fetch_first_card_bookmaker_probs
    from odds.goalscorer import fetch_goalscorer_probabilities_from_event
    from odds.player_props import fetch_event_player_props_by_id

    fetch_result = fetch_odds(sport=sport, region=region, force_refresh=refresh)
    event = find_event(fetch_result.events, roster.home, roster.away)
    match = event_to_match_data(event)
    kickoff = roster.kickoff or str(event.get("commence_time", ""))
    event_id = str(event.get("id", ""))

    need_scrape_match = use_scrape and _needs_correct_score(match.odds)
    prefetch = MatchPrefetch()

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures: dict[str, object] = {}

        if use_oddspapi and oddspapi_configured():
            futures["op_match"] = pool.submit(
                fetch_oddspapi_match_odds,
                roster.home,
                roster.away,
                kickoff_iso=kickoff,
            )
            futures["op_props"] = pool.submit(
                fetch_oddspapi_player_props,
                roster.home,
                roster.away,
                kickoff,
            )

        if need_scrape_match:
            futures["scrape"] = pool.submit(
                fetch_scraped_match_odds,
                roster.home,
                roster.away,
                match.odds,
                kickoff_iso=kickoff,
            )

        if use_scrape:
            futures["sofa"] = pool.submit(
                fetch_sofascore_player_props,
                roster.home,
                roster.away,
                kickoff,
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

        if use_oddspapi or use_scrape:
            futures["first_card"] = pool.submit(
                fetch_first_card_bookmaker_probs,
                roster,
            )

        if event_id:
            futures["goalscorer"] = pool.submit(
                fetch_goalscorer_probabilities_from_event,
                event_id,
                sport=sport,
                region=region,
                force_refresh=refresh,
            )
            futures["event_props"] = pool.submit(
                fetch_event_player_props_by_id,
                event_id,
                sport=sport,
                region=region,
                force_refresh=refresh,
            )

        sources = ["The Odds API"]

        if "op_match" in futures:
            try:
                op_odds = futures["op_match"].result()
                match = merge_match_data(match, op_odds)
                sources.append("OddsPapi")
            except (RuntimeError, ValueError) as exc:
                print(f"  [warn] OddsPapi non disponibile: {exc}", file=sys.stderr)

        if "scrape" in futures:
            try:
                scrape_overlay, scrape_sources = futures["scrape"].result()
                match = merge_match_data_fill_gaps(match, scrape_overlay)
                sources.extend(scrape_sources)
            except ValueError as exc:
                print(f"  [warn] Scraping non disponibile: {exc}", file=sys.stderr)

        if "op_props" in futures:
            try:
                prefetch.oddspapi_props = futures["op_props"].result()
            except (RuntimeError, ValueError):
                pass

        if "sofa" in futures:
            try:
                prefetch.sofa_props = futures["sofa"].result()
            except RuntimeError:
                pass

        prefetch.sub_profiles = {
            "home": futures["sub_home"].result(),
            "away": futures["sub_away"].result(),
        }

        if "first_card" in futures:
            try:
                prefetch.first_card = futures["first_card"].result()
            except (RuntimeError, ValueError):
                pass

        if "goalscorer" in futures:
            try:
                prefetch.goalscorer_probs = futures["goalscorer"].result()
            except RuntimeError:
                prefetch.goalscorer_probs = {}

        if "event_props" in futures:
            try:
                prefetch.event_player_props = futures["event_props"].result()
            except RuntimeError:
                pass

    cache_note = "cache" if fetch_result.from_cache else "live"
    source_note = f"{' + '.join(sources)} ({cache_note})"
    return match, source_note, fetch_result.requests_remaining, event_id, prefetch
