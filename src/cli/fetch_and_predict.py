"""Fetch odds from both APIs and run result prediction."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

from odds.api_client import fetch_odds, get_api_key, load_env_file
from odds.api_normalize import event_to_match_data, find_event, list_events
from odds.match_loader import MatchOdds
from odds.merge_providers import merge_match_data, merge_match_data_fill_gaps
from odds.oddspapi_client import oddspapi_configured
from odds.oddspapi_normalize import fetch_oddspapi_match_odds
from odds.scrape_normalize import fetch_scraped_match_odds
from predict.ev_report import print_ev_report, result_recommendation_to_report
from predict.result_ev import rank_predictions


def _needs_correct_score(odds: MatchOdds) -> bool:
    return not odds.correct_score or not odds.half_time_correct_score


def _build_match_from_apis(
    home: str,
    away: str,
    *,
    sport: str,
    region: str,
    refresh: bool,
    use_oddspapi: bool,
    use_scrape: bool,
    kickoff_iso: str | None = None,
):
    """Fetch and merge The Odds API + OddsPapi + web scrape for one fixture."""
    fetch_result = fetch_odds(sport=sport, region=region, force_refresh=refresh)
    event = find_event(fetch_result.events, home, away)
    match = event_to_match_data(event)
    kickoff = kickoff_iso or str(event.get("commence_time", ""))

    sources = ["The Odds API"]
    op_future = None
    scrape_future = None

    with ThreadPoolExecutor(max_workers=2) as pool:
        if use_oddspapi and oddspapi_configured():
            op_future = pool.submit(
                fetch_oddspapi_match_odds, home, away, kickoff_iso=kickoff
            )
        if use_scrape and _needs_correct_score(match.odds):
            scrape_future = pool.submit(
                fetch_scraped_match_odds,
                home,
                away,
                match.odds,
                kickoff_iso=kickoff,
            )

        if op_future is not None:
            try:
                op_odds = op_future.result()
                match = merge_match_data(match, op_odds)
                sources.append("OddsPapi")
            except (RuntimeError, ValueError) as exc:
                print(f"  [warn] OddsPapi non disponibile: {exc}", file=sys.stderr)
        elif use_oddspapi:
            print(
                "  [warn] OddsPapi non configurato — vedi docs/API_SETUP.md",
                file=sys.stderr,
            )

        if scrape_future is not None:
            try:
                scrape_overlay, scrape_sources = scrape_future.result()
                match = merge_match_data_fill_gaps(match, scrape_overlay)
                sources.extend(scrape_sources)
            except ValueError as exc:
                print(f"  [warn] Scraping non disponibile: {exc}", file=sys.stderr)

    cache_note = "cache" if fetch_result.from_cache else "live"
    source_note = f"{' + '.join(sources)} ({cache_note})"
    return match, source_note, fetch_result.requests_remaining


def print_match_recommendation(
    match,
    *,
    source_note: str,
    top_n: int = 5,
) -> None:
    dist, ranked = rank_predictions(match, top_n=top_n)
    if not ranked:
        print(f"  Nessuna raccomandazione per {match.home} - {match.away}")
        return

    report = result_recommendation_to_report(
        match.home,
        match.away,
        match_id=match.match_id,
        kickoff=match.kickoff,
        source_note=source_note,
        dist=dist,
        best=ranked[0],
        ranked=ranked,
        top_n=top_n,
    )
    print_ev_report(report)


def run_list(sport: str, region: str, refresh: bool) -> int:
    fetch_result = fetch_odds(sport=sport, region=region, force_refresh=refresh)
    events = list_events(fetch_result.events)
    if not events:
        print("Nessuna partita in calendario The Odds API al momento.")
        return 0

    cache_note = "cache" if fetch_result.from_cache else "API live"
    print(f"Partite disponibili ({cache_note}, n={len(events)}):")
    for idx, ev in enumerate(events, start=1):
        print(f"  {idx}. {ev.home} vs {ev.away}  |  {ev.kickoff}")
    if fetch_result.requests_remaining:
        print(f"Crediti Odds API rimanenti: {fetch_result.requests_remaining}")
    return 0


def run_match(
    home: str,
    away: str,
    sport: str,
    region: str,
    refresh: bool,
    top_n: int,
    use_oddspapi: bool,
    use_scrape: bool,
) -> int:
    fetch_result = fetch_odds(sport=sport, region=region, force_refresh=refresh)
    event = find_event(fetch_result.events, home, away)
    match, source_note, remaining = _build_match_from_apis(
        home,
        away,
        sport=sport,
        region=region,
        refresh=False,
        use_oddspapi=use_oddspapi,
        use_scrape=use_scrape,
        kickoff_iso=str(event.get("commence_time", "")),
    )
    print_match_recommendation(match, source_note=source_note, top_n=top_n)
    if remaining:
        print(f"\nCrediti Odds API rimanenti: {remaining}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()

    parser = argparse.ArgumentParser(
        description="Raccomandazione risultato FM per una partita (--home + --away obbligatori)"
    )
    parser.add_argument("--home", help="Squadra casa (IT o EN)")
    parser.add_argument("--away", help="Squadra ospite (IT o EN)")
    parser.add_argument("--list", action="store_true", help="Solo elenco partite, senza calcolo")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-oddspapi", action="store_true", help="Salta OddsPapi")
    parser.add_argument("--no-scrape", action="store_true", help="Salta scraping web")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--sport", default="soccer_fifa_world_cup")
    parser.add_argument("--region", default="eu")
    args = parser.parse_args(argv)

    try:
        get_api_key()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    use_oddspapi = not args.no_oddspapi
    use_scrape = not args.no_scrape

    if args.list:
        return run_list(args.sport, args.region, args.refresh)

    if not args.home or not args.away:
        parser.error("Specifica --home e --away per la partita da analizzare (oppure --list)")

    try:
        return run_match(
            args.home,
            args.away,
            args.sport,
            args.region,
            args.refresh,
            args.top,
            use_oddspapi,
            use_scrape,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
