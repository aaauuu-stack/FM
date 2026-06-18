"""Timing per singola voce del pipeline (HTTP reale, usa cache se presente)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

HOME, AWAY = "Uzbekistan", "Colombia"
KICKOFF = "2026-06-17T17:45:00Z"


def _sec(label: str, fn) -> float:
    t0 = time.perf_counter()
    try:
        fn()
        status = "OK"
    except Exception as exc:
        status = f"ERR ({exc.__class__.__name__}: {str(exc)[:80]})"
    elapsed = time.perf_counter() - t0
    print(f"  {label:<42} {elapsed:6.2f}s  {status}")
    return elapsed


def main() -> int:
    from odds.api_client import fetch_odds
    from odds.api_normalize import find_event
    from odds.event_odds_bundle import fetch_combined_event_player_odds
    from odds.oddspapi_bundle import fetch_oddspapi_bundle
    from odds.oddspapi_client import fetch_fixtures, fetch_markets_catalog, fetch_odds as op_fetch_odds
    from odds.oddspapi_normalize import lookup_oddspapi_fixture
    from odds.sofascore_bundle import (
        _fetch_odds_markets,
        fetch_sofascore_bundle,
        sofascore_event_id_from_oddspapi,
    )
    from players.screen_parse import roster_from_ocr_text

    sample_ocr = """
    Inghilterra vs Croazia
    Portieri
    Pickford +10 +4
    Livakovic +10 +5
    Attaccanti
    Kane +3
    Kramaric +5
    Centrocampisti
    Modric +6
    Sucic +12 vice
    """

    print(f"Benchmark voci singole — {HOME} vs {AWAY}\n")
    print(f"  {'Voce':<42} {'Tempo':>6}  Esito")
    print("  " + "-" * 62)

    rows: list[tuple[str, float]] = []

    rows.append(("OCR parse testo (no immagine)", _sec("OCR parse testo (no immagine)", lambda: roster_from_ocr_text(sample_ocr))))

    print("\n  --- The Odds API ---")
    event_id: str | None = None

    def _odds_listing():
        nonlocal event_id
        r = fetch_odds(sport="soccer_fifa_world_cup", region="eu", force_refresh=False)
        ev = find_event(r.events, HOME, AWAY)
        event_id = str(ev.get("id", ""))

    rows.append(("The Odds API — listing partite", _sec("The Odds API — listing partite", _odds_listing)))

    if event_id:
        rows.append(
            (
                "The Odds API — goalscorer+props evento",
                _sec(
                    "The Odds API — goalscorer+props evento",
                    lambda: fetch_combined_event_player_odds(
                        event_id, sport="soccer_fifa_world_cup", region="eu"
                    ),
                ),
            )
        )

    print("\n  --- OddsPapi ---")
    rows.append(("OddsPapi — catalogo mercati", _sec("OddsPapi — catalogo mercati", fetch_markets_catalog)))

    fixture_holder: list = []

    def _op_fixture():
        fixture_holder.append(lookup_oddspapi_fixture(HOME, AWAY, KICKOFF))

    rows.append(("OddsPapi — lookup fixture", _sec("OddsPapi — lookup fixture", _op_fixture)))

    if fixture_holder:
        fid = str(fixture_holder[0]["fixtureId"])
        rows.append(
            (
                "OddsPapi — quote fixture",
                _sec("OddsPapi — quote fixture", lambda: op_fetch_odds(fid)),
            )
        )

    rows.append(
        (
            "OddsPapi — bundle completo",
            _sec(
                "OddsPapi — bundle completo",
                lambda: fetch_oddspapi_bundle(HOME, AWAY, KICKOFF),
            ),
        )
    )

    print("\n  --- SofaScore lite ---")
    sofa_id_holder: list = []

    def _resolve_id():
        eid = sofascore_event_id_from_oddspapi(HOME, AWAY, KICKOFF)
        sofa_id_holder.append(eid)

    rows.append(
        (
            "SofaScore — sofascoreId da OddsPapi",
            _sec("SofaScore — sofascoreId da OddsPapi", _resolve_id),
        )
    )

    if sofa_id_holder and sofa_id_holder[0]:
        eid = sofa_id_holder[0]
        rows.append(
            (
                "SofaScore — quote evento (/odds/1/all)",
                _sec(
                    "SofaScore — quote evento (/odds/1/all)",
                    lambda: _fetch_odds_markets(eid),
                ),
            )
        )

    print("\n  --- SofaScore (parse locale, ~0s) ---")
    print("  (correct score, P(gol), P(cart), first card = parse da stesso payload)")

    rows.append(
        (
            "SofaScore — bundle lite",
            _sec(
                "SofaScore — bundle lite",
                lambda: fetch_sofascore_bundle(
                    HOME,
                    AWAY,
                    KICKOFF,
                    need_match_cs=True,
                    need_goal_props=True,
                    need_card_props=True,
                    need_first_card=True,
                ),
            ),
        )
    )

    print("\n  --- Riepilogo ---")
    total = sum(r[1] for r in rows)
    print(f"  Somma sequenziale (peggio caso): {total:.1f}s")
    print("  Nota: in produzione OddsPapi+SofaScore+API corrono in parallelo.")
    print("        Tempo reale ~ max(voci lente), non la somma.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
