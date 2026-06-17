"""Verify The Odds API and OddsPapi credentials."""

from __future__ import annotations

import argparse
import sys

from odds.api_client import fetch_odds, get_api_key, load_env_file
from odds.oddspapi_client import fetch_markets_catalog, get_oddspapi_key, oddspapi_configured
from odds.match_loader import MatchOdds
from odds.oddspapi_normalize import _discover_market_ids, fetch_oddspapi_match_odds
from odds.scrape_normalize import fetch_scraped_match_odds


def test_odds_api(sport: str, region: str) -> bool:
    print("=== The Odds API ===")
    try:
        key = get_api_key()
        print(f"  API key: {key[:8]}...{key[-4:]}")
    except RuntimeError as exc:
        print(f"  FAIL: {exc}")
        return False

    try:
        result = fetch_odds(sport=sport, region=region, force_refresh=True)
        n = len(result.events)
        print(f"  OK — {n} partite per {sport}")
        if result.requests_remaining:
            print(f"  Crediti rimanenti: {result.requests_remaining}")
        if n > 0:
            ev = result.events[0]
            print(f"  Esempio: {ev.get('home_team')} vs {ev.get('away_team')}")
        return True
    except RuntimeError as exc:
        print(f"  FAIL: {exc}")
        return False


def test_oddspapi_catalog() -> bool:
    print("\n=== OddsPapi (catalogo mercati) ===")
    if not oddspapi_configured():
        print("  SKIP — ODDSPAPI_API_KEY non impostata in .env")
        return False

    try:
        key = get_oddspapi_key()
        print(f"  API key: {key[:8]}...{key[-4:]}")
        catalog = fetch_markets_catalog()
        ft_id, ht_id = _discover_market_ids(catalog)
        print(f"  OK — {len(catalog)} mercati calcio nel catalogo")
        print(f"  Correct Score FT marketId: {ft_id}")
        print(f"  Correct Score 1T marketId: {ht_id}")
        return ft_id is not None
    except RuntimeError as exc:
        print(f"  FAIL: {exc}")
        return False


def test_oddspapi_match(home: str, away: str) -> bool:
    print(f"\n=== OddsPapi (partita {home} vs {away}) ===")
    if not oddspapi_configured():
        print("  SKIP")
        return False

    try:
        odds = fetch_oddspapi_match_odds(home, away)
        print(f"  OK — FT scores: {len(odds.correct_score)} | HT scores: {len(odds.half_time_correct_score)}")
        if odds.correct_score:
            print(f"  Esempio FT: {list(odds.correct_score.items())[:3]}")
        return bool(odds.correct_score)
    except (RuntimeError, ValueError) as exc:
        print(f"  FAIL: {exc}")
        return False


def test_scrape_match(home: str, away: str) -> bool:
    print(f"\n=== Web scrape (SofaScore, {home} vs {away}) ===")
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        print("  SKIP — installa curl_cffi: pip install curl_cffi")
        return True

    existing = MatchOdds()
    try:
        overlay, sources = fetch_scraped_match_odds(home, away, existing)
        print(
            f"  OK — fonti: {', '.join(sources)} | "
            f"FT: {len(overlay.correct_score)} | HT: {len(overlay.half_time_correct_score)}"
        )
        if overlay.correct_score:
            print(f"  Esempio FT: {list(overlay.correct_score.items())[:3]}")
        return bool(overlay.correct_score)
    except (RuntimeError, ValueError) as exc:
        print(f"  FAIL: {exc}")
        return False


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Test The Odds API + OddsPapi + scrape")
    parser.add_argument("--odds-only", action="store_true")
    parser.add_argument("--oddspapi-only", action="store_true")
    parser.add_argument("--scrape-only", action="store_true")
    parser.add_argument("--home", default="England")
    parser.add_argument("--away", default="Croatia")
    parser.add_argument("--sport", default="soccer_fifa_world_cup")
    parser.add_argument("--region", default="eu")
    args = parser.parse_args(argv)

    ok = True
    if args.scrape_only:
        ok = test_scrape_match(args.home, args.away) and ok
    elif args.oddspapi_only:
        ok = test_oddspapi_catalog() and ok
        ok = test_oddspapi_match(args.home, args.away) and ok
    else:
        if not args.oddspapi_only:
            ok = test_odds_api(args.sport, args.region) and ok
        if not args.odds_only:
            ok = test_oddspapi_catalog() and ok
            ok = test_oddspapi_match(args.home, args.away) and ok
            ok = test_scrape_match(args.home, args.away) and ok

    print("\n" + ("Tutto OK" if ok else "Alcuni test falliti — vedi docs/API_SETUP.md"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
