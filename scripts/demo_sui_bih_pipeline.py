"""Demo pipeline Svizzera–Bosnia from user screenshots (no live API)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odds.devig import independent_implied_probs
from odds.goalscorer import (
    apply_goalscorer_probs,
    attach_clean_sheet_probs,
    estimate_clean_sheet_probs_from_match,
)
from odds.match_loader import MatchData, MatchOdds
from players.models import MatchRoster, PlayerBonus
from players.roster_normalize import normalize_parsed_roster
from players.starters import apply_starter_probabilities, infer_starters
from predict.lineup_ev import optimize_lineup, rank_players
from scoring.lineup_rules import gk_clean_sheet_bonus

# ── STEP 1: dati letti dagli screenshot ─────────────────────────────
RAW = [
    ("Keller", "home", "GK", 5),
    ("Kobel", "home", "GK", 5),
    ("Mvogo", "home", "GK", 5),
    ("Hadzikic", "away", "GK", 6),
    ("Zlomislic", "away", "GK", 6),
    ("Vasilj", "away", "GK", 6),
    ("Amdouni", "home", "FWD", 7),
    ("Okafor", "home", "FWD", 7),
    ("Embolo", "home", "FWD", 5),
    ("Itten", "home", "FWD", 9),
    ("Alajbegovic", "away", "FWD", 8),
    ("Bajraktarevic", "away", "FWD", 7),
    ("Bazdar", "away", "FWD", 12),
    ("Demirovic", "away", "FWD", 4),
    ("Dzeko", "away", "FWD", 6),
    ("Lukic", "away", "FWD", 11),
    ("Tabakovic", "away", "FWD", 12),
    ("Aebischer", "home", "MID", 8),
    ("Ndoye", "home", "MID", 6, True),
    ("Vargas R.", "home", "MID", 7),
    ("Manzambi", "home", "MID", 8),
    ("Rieder", "home", "MID", 8),
    ("Zakaria D.", "home", "MID", 8),
    ("Fassnacht", "home", "MID", 10),
    ("Xhaka", "home", "MID", 8),
    ("Freuler", "home", "MID", 9),
    ("Jashari", "home", "MID", 8),
    ("Sow", "home", "MID", 9),
    ("Burnic", "away", "MID", 12),
    ("Basic", "away", "MID", 11),
    ("Gigovic", "away", "MID", 11),
    ("Tahirovic", "away", "MID", 8),
    ("Hadziahmetovic", "away", "MID", 11),
    ("Mahmic", "away", "MID", 12),
    ("Memic", "away", "MID", 8),
    ("Sunjic", "away", "MID", 8),
    ("Akanji", "home", "DEF", 8),
    ("Amenda", "home", "DEF", 11),
    ("Comert", "home", "DEF", 12),
    ("Elvedi", "home", "DEF", 8),
    ("Jaquez", "home", "DEF", 11),
    ("Muheim", "home", "DEF", 10),
    ("Widmer", "home", "DEF", 9),
    ("Rodriguez R.", "home", "DEF", 9),
    ("Dedic", "away", "DEF", 8),
    ("Celik N.", "away", "DEF", 12),
    ("Katic", "away", "DEF", 9),
    ("Hadzikadunic", "away", "DEF", 11),
    ("Mujakic", "away", "DEF", 12),
    ("Kolasinac", "away", "DEF", 9),
    ("Muharemovic", "away", "DEF", 8),
    ("Radeljic", "away", "DEF", 13),
]

players: list[PlayerBonus] = []
for row in RAW:
    vice = row[4] if len(row) > 4 else False
    bg = row[3]
    players.append(
        PlayerBonus(
            row[0],
            row[1],
            row[2],
            bonus_goal=bg,
            bonus_clean_sheet=bg if row[2] == "GK" else 0,
            vice_allenatore=vice,
        )
    )
players = normalize_parsed_roster(players)
roster = MatchRoster("SUI-BIH", "Svizzera", "Bosnia-Erzegovina", "2026-06-18", players)

print("=" * 60)
print("STEP 1 - LETTURA SCREENSHOT -> MatchRoster")
print("=" * 60)
print(f"Partita: {roster.home} vs {roster.away}")
vice = roster.vice_player()
print(f"Giocatori: {len(roster.players)} | Vice: {vice.name} (+{vice.bonus_goal})")
print("Portieri (bonus gol / porta inviolata):")
for p in roster.players:
    if p.is_goalkeeper:
        print(f"  {p.side:4} {p.name:12} +{p.bonus_goal} / +{p.bonus_clean_sheet}")

# ── STEP 2: quote book (ricerca online utente) ──────────────────────
print()
print("=" * 60)
print("STEP 2 - QUOTE BOOK -> P(gol)  [1/quota, senza normalizzare tutto il mercato]")
print("=" * 60)
BOOK_ODDS = {
    "Embolo": 2.095,
    "Itten": 2.67,
    "Amdouni": 2.73,
    "Ndoye": 3.6,
    "Vargas": 3.8,
    "Dzeko": 4.5,
    "Tabakovic": 5.0,
    "Demirovic": 3.2,
}
p_gol = independent_implied_probs(BOOK_ODDS)
for name, prob in sorted(p_gol.items(), key=lambda x: -x[1]):
    print(f"  {name:12} quota {BOOK_ODDS[name]:.2f} -> P(gol)={prob * 100:.1f}%")

roster, _ = apply_goalscorer_probs(roster, p_gol)

match = MatchData(
    "SUI-BIH",
    "Svizzera",
    "Bosnia-Erzegovina",
    "2026-06-18",
    MatchOdds(
        h2h={"home": 1.55, "draw": 4.0, "away": 5.5},
        totals={"line": 2.5, "over": 1.85, "under": 1.95},
    ),
)

print()
print("=" * 60)
print("STEP 3 - P(gol) assegnate al roster (match nomi)")
print("=" * 60)
for target in ["Embolo", "Itten", "Amdouni", "Ndoye", "Vargas R.", "Dzeko", "Tabakovic", "Keller"]:
    player = next((p for p in roster.players if p.name == target), None)
    if player:
        print(
            f"  {player.name:14} bonus+{player.bonus_goal}  "
            f"P(gol)={float(player.p_goal or 0) * 100:.1f}%  "
            f"book={player.book_goal_matched}"
        )

# ── STEP 4: titolari ───────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 4 - TITOLARI (SofaScore XI -> infer_starters)")
print("=" * 60)
SOFA_HOME = {
    "Kobel", "G. Kobel", "Embolo", "B. Embolo", "Ndoye", "D. Ndoye", "Vargas", "R. Vargas",
    "Xhaka", "G. Xhaka", "Freuler", "R. Freuler", "Akanji", "M. Akanji", "Elvedi",
    "Rodriguez", "R. Rodriguez", "Widmer", "J. Widmer", "Zakaria",
}
SOFA_AWAY = {
    "Vasilj", "N. Vasilj", "Dzeko", "E. Dzeko", "Demirovic", "Dedic", "A. Dedic",
    "Kolasinac", "Basic", "Tahirovic", "Katic", "Muharemovic", "Memic",
}
with patch(
    "players.starters.fetch_event_starter_names",
    return_value=(SOFA_HOME, SOFA_AWAY, "lineups SofaScore (11+11 titolari)"),
):
    roster, starter_note = infer_starters(roster, sofascore_event_id=15186806)
print(f"Nota: {starter_note}")
starters = [p for p in roster.players if p.starter]
home_n = sum(1 for p in starters if p.side == "home")
away_n = sum(1 for p in starters if p.side == "away")
print(f"Titolari: {len(starters)} ({home_n} casa + {away_n} ospiti)")
for side in ("home", "away"):
    names = ", ".join(p.name for p in starters if p.side == side)
    print(f"  [{side}] {names}")

# ── STEP 5: CS + zero panchina ──────────────────────────────────────
roster = attach_clean_sheet_probs(roster, match)
roster = apply_starter_probabilities(roster)
p_home_cs, p_away_cs = estimate_clean_sheet_probs_from_match(match)

print()
print("=" * 60)
print("STEP 5 - PROBABILITA FINALI (panchina azzerata)")
print("=" * 60)
print(f"P(porta inviolata) da quote 1X2/O-U: Svizzera {p_home_cs * 100:.1f}% | Bosnia {p_away_cs * 100:.1f}%")
for gk_name in ("Kobel", "Keller", "Vasilj", "Hadzikic"):
    gk = next(p for p in roster.players if p.name == gk_name)
    print(
        f"  {gk.name:10} starter={gk.starter}  "
        f"P(CS)={float(gk.p_clean_sheet or 0) * 100:.1f}%  bonus CS=+{gk_clean_sheet_bonus(gk)}"
    )
print("Attaccanti / centrocampisti chiave:")
for name in ("Embolo", "Amdouni", "Itten", "Dzeko", "Demirovic", "Vargas R."):
    p = next(x for x in roster.players if x.name == name)
    print(f"  {p.name:12} starter={p.starter}  P(gol)={float(p.p_goal or 0) * 100:.1f}%")

# ── STEP 6: EV e formazione ─────────────────────────────────────────
print()
print("=" * 60)
print("STEP 6 - EV -> FORMAZIONE (4 giocatori + vice Ndoye fisso)")
print("=" * 60)
for pev in rank_players(roster, top_n=8):
    print(
        f"  {pev.player.name:14} ({pev.player.role}) +{pev.player.bonus_goal}  "
        f"P(gol)={pev.p_goal_action * 100:.1f}%  EV={pev.ev_total:.3f} pt"
    )

best, alts = optimize_lineup(roster)
print()
print("Formazione consigliata:")
for pev in best.players:
    parts = ", ".join(f"{k}={v:.3f}" for k, v in pev.breakdown.items())
    print(f"  {pev.player.name:14} EV={pev.ev_total:.3f}  ({parts})")
print(f"\nEV totale formazione: {best.ev_total:.3f} pt")
if alts:
    print("Alternative top-3:")
    for alt in alts[:3]:
        print(f"  {' | '.join(alt.names)}  EV={alt.ev_total:.3f}")
