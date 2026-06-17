"""CLI entry point for result prediction."""

from __future__ import annotations

import argparse
import sys

from odds.match_loader import load_match
from predict.ev_report import print_ev_report, result_recommendation_to_report
from predict.result_ev import rank_predictions


def print_recommendation(match_path: str, top_n: int = 5) -> int:
    match = load_match(match_path)
    dist, ranked = rank_predictions(match, top_n=top_n)

    if not ranked:
        print("Nessuna raccomandazione disponibile: quote insufficienti.", file=sys.stderr)
        return 1

    source_note = f"{dist.source} | confidenza {dist.confidence}"
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
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fantamondiale 2026 — raccomandazione risultato (H, I, J, superbonus)"
    )
    parser.add_argument(
        "--match",
        required=True,
        help="Path al file YAML della partita (es. data/matches/eng-cro.yaml)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Numero di alternative da mostrare (default: 5)",
    )
    args = parser.parse_args(argv)
    return print_recommendation(args.match, top_n=args.top)


if __name__ == "__main__":
    raise SystemExit(main())
