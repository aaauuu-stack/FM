"""Internal benchmark: timing per fase del pipeline analisi.

Usage:
  py -3 scripts/bench_pipeline.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from odds.request_cache import clear_request_cache
from odds.sofascore_bundle import SofaScoreBundle
from players.models import MatchRoster, PlayerBonus
from players.screen_parse import roster_from_ocr_text
from predict.analyze import analyze_match_from_roster
from predict.timing import reset_timings, timed, timing_summary

UZB_COL_FM = """
SCELTA CALCIATORI
UZBEKISTAN - COLOMBIA
Portieri
ERGASHEV +14  MONTERO +5
NEMATOV +14   OSPINA +5
Attaccanti
AMANOV +12    CORDOBA JH. +10
KHAMDAMOV +13 DIAZ L. +4
SERGEEV +12   HERNANDEZ C. +8
SHOMURODOV +10 SUAREZ L. +5
Centrocampisti
ABDULLAEV +13 ARIAS J. +6
ESANOV +13    CAMPAZ +9
"""


def _eng_cro_roster() -> MatchRoster:
    return MatchRoster(
        match_id="ENG-CRO",
        home="England",
        away="Croatia",
        kickoff="2026-06-17T20:00:00Z",
        players=[
            PlayerBonus("Kane", "home", "FWD", bonus_goal=3),
            PlayerBonus("Toney", "home", "FWD", bonus_goal=9),
            PlayerBonus("Pickford", "home", "GK", bonus_goal=10, bonus_clean_sheet=4),
            PlayerBonus("Modric", "away", "MID", bonus_goal=6),
            PlayerBonus("Kramaric", "away", "FWD", bonus_goal=5),
            PlayerBonus("Livakovic", "away", "GK", bonus_goal=10, bonus_clean_sheet=5),
            PlayerBonus("Sucic", "away", "MID", bonus_goal=12, vice_allenatore=True),
            PlayerBonus("Bellingham", "home", "MID", bonus_goal=7),
        ],
    )


def _empty_sofa_bundle() -> SofaScoreBundle:
    return SofaScoreBundle(
        goal_probs={},
        card_probs={},
        props_note="mock: sofa skip",
    )


def _run(label: str, fn) -> float:
    reset_timings()
    clear_request_cache()
    t0 = time.perf_counter()
    try:
        fn()
        ok = "OK"
    except Exception as exc:
        ok = f"ERR: {exc}"
    elapsed = time.perf_counter() - t0
    print(f"\n=== {label} ===")
    print(f"  Totale: {elapsed:.2f}s  ({ok})")
    print(f"  Step:   {timing_summary()}")
    return elapsed


def main() -> int:
    print("Benchmark pipeline FM (locale, cache disco se presente)\n")

    _run("1. OCR parse testo (Uzbekistan-Colombia, no Tesseract)", lambda: roster_from_ocr_text(UZB_COL_FM))

    roster = _eng_cro_roster()

    _run(
        "2a. Analisi ENG-CRO — solo The Odds API (no OddsPapi, no scrape)",
        lambda: analyze_match_from_roster(
            roster, refresh=False, use_oddspapi=False, use_scrape=False
        ),
    )

    _run(
        "2b. Analisi ENG-CRO — cache, OddsPapi+API, NO scrape",
        lambda: analyze_match_from_roster(
            roster, refresh=False, use_oddspapi=True, use_scrape=False
        ),
    )

    with patch("predict.prefetch.fetch_sofascore_bundle", return_value=_empty_sofa_bundle()):
        _run(
            "3. Analisi completa ENG-CRO — cache, sofa MOCK (0s)",
            lambda: analyze_match_from_roster(
                roster, refresh=False, use_oddspapi=True, use_scrape=True
            ),
        )

    def _slow_sofa(*_a, **_k):
        time.sleep(8.0)
        return _empty_sofa_bundle()

    with patch("predict.prefetch.fetch_sofascore_bundle", side_effect=_slow_sofa):
        _run(
            "4. Analisi ENG-CRO — sofa MOCK lento (8s, simula Render)",
            lambda: analyze_match_from_roster(
                roster, refresh=False, use_oddspapi=True, use_scrape=True
            ),
        )

    # Conta chiamate scrape reali (timeout 15s ciascuna su cloud) — max 1 tentativo breve
    scrape_calls = 0

    def _counting_fetch_json(url, **kwargs):
        nonlocal scrape_calls
        scrape_calls += 1
        raise RuntimeError("bench: stop after counting")

    try:
        from odds import scrape_client

        with patch.object(scrape_client, "fetch_json", side_effect=_counting_fetch_json):
            reset_timings()
            clear_request_cache()
            t0 = time.perf_counter()
            try:
                analyze_match_from_roster(
                    roster, refresh=False, use_oddspapi=True, use_scrape=True
                )
            except Exception:
                pass
            elapsed = time.perf_counter() - t0
            print(f"\n=== 5. SofaScore LIVE (interrotto al 1° fetch) ===")
            print(f"  Chiamate scrape tentate: {scrape_calls}")
            print(f"  Tempo prima del blocco: {elapsed:.2f}s")
            print(f"  Step: {timing_summary()}")
            print(
                "  Stima worst-case Render (12s/req): "
                f"{scrape_calls * 12:.0f}s se sequenziale, "
                f"~{max(12, scrape_calls // 2 * 12)}s con parallelismo attuale"
            )
    except Exception as exc:
        print(f"\n=== 5. SofaScore LIVE — skip: {exc} ===")

    print("\n--- Fine benchmark ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
