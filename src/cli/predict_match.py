"""Unified match prediction: results + events K/L + lineup (regolamento completo)."""

from __future__ import annotations

import argparse
import sys

from odds.api_client import get_api_key, load_env_file
from predict.analyze import analyze_match
from predict.ev_report import print_ev_report


def run_match_with_roster(
    home: str,
    away: str,
    roster_path: str,
    *,
    sport: str,
    region: str,
    refresh: bool,
    use_oddspapi: bool,
    use_scrape: bool,
    top_n: int,
) -> int:
    analysis = analyze_match(
        home,
        away,
        roster_path,
        sport=sport,
        region=region,
        refresh=refresh,
        use_oddspapi=use_oddspapi,
        use_scrape=use_scrape,
        top_n=top_n,
    )

    if analysis.result:
        print_ev_report(analysis.result)
    if analysis.first_sub:
        print_ev_report(analysis.first_sub)
    if analysis.first_card:
        print_ev_report(analysis.first_card)
    if analysis.lineup:
        print_ev_report(analysis.lineup)

    print(f"\n{'=' * 60}")
    print(f"EV formazione (4+vice): {analysis.lineup_ev:.3f} pt")
    if analysis.events_ev:
        print(f"EV eventi K+L: {analysis.events_ev:.3f} pt")
    print("(EV risultato H/I/J stampato sopra — EV giornata = somma di tutti i blocchi)")

    if analysis.requests_remaining:
        print(f"\nCrediti Odds API rimanenti: {analysis.requests_remaining}")

    if analysis.vice_name:
        print(
            f"\nVice allenatore (fisso dallo screen): {analysis.vice_name} "
            f"(bonus +{analysis.vice_bonus})"
        )

    if analysis.top_players:
        print("\nTop giocatori per EV singolo (escluso vice):")
        for pev in analysis.top_players:
            malus_note = f", malus -{pev.ev_malus:.2f}" if pev.ev_malus else ""
            print(
                f"  {pev.player.name} ({pev.player.role}, bonus +{pev.player.bonus_goal}): "
                f"EV={pev.ev_total:.3f} pt{malus_note}"
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(
        description="Raccomandazione risultato + formazione FM (richiede roster da screenshot)"
    )
    parser.add_argument("--home", required=True, help="Squadra casa (IT o EN)")
    parser.add_argument("--away", required=True, help="Squadra ospite (IT o EN)")
    parser.add_argument(
        "--roster",
        required=True,
        help="YAML bonus giocatori (es. data/players/eng-cro.yaml)",
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-oddspapi", action="store_true")
    parser.add_argument("--no-scrape", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--sport", default="soccer_fifa_world_cup")
    parser.add_argument("--region", default="eu")
    args = parser.parse_args(argv)

    try:
        get_api_key()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        return run_match_with_roster(
            args.home,
            args.away,
            args.roster,
            sport=args.sport,
            region=args.region,
            refresh=args.refresh,
            use_oddspapi=not args.no_oddspapi,
            use_scrape=not args.no_scrape,
            top_n=args.top,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
