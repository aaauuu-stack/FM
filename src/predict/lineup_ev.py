"""Lineup EV ranking and 4-player (+ vice) optimizer."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from players.models import MatchRoster, PlayerBonus
from scoring.lineup_points import PlayerEv, compute_player_ev
from scoring.lineup_rules import LINEUP_SIZE


@dataclass
class LineupRecommendation:
    players: list[PlayerEv]  # 4 scelte personali
    ev_total: float
    vice: PlayerEv | None = None

    @property
    def all_players(self) -> list[PlayerEv]:
        if self.vice:
            return self.players + [self.vice]
        return self.players

    @property
    def names(self) -> list[str]:
        names = [p.player.name for p in self.players]
        if self.vice:
            names.append(f"{self.vice.player.name} (VA)")
        return names


def rank_players(roster: MatchRoster, top_n: int = 10) -> list[PlayerEv]:
    pool = roster.lineup_pool()
    ranked = [compute_player_ev(p) for p in pool]
    ranked.sort(key=lambda p: (-p.ev_total, p.player.name.lower()))
    return ranked[:top_n]


def _valid_lineup(players: list[PlayerBonus]) -> bool:
    if len(players) != LINEUP_SIZE:
        return False
    sides = {p.side for p in players}
    if "home" not in sides or "away" not in sides:
        return False
    for side in ("home", "away"):
        gks = sum(1 for p in players if p.is_goalkeeper and p.side == side)
        if gks > 1:
            return False
    return True


def _build_recommendation(
    combo: tuple[PlayerBonus, ...],
    vice: PlayerEv | None,
) -> LineupRecommendation:
    evs = [compute_player_ev(p) for p in combo]
    total = sum(ev.ev_total for ev in evs)
    if vice:
        total += vice.ev_total
    return LineupRecommendation(players=evs, ev_total=total, vice=vice)


def optimize_lineup(
    roster: MatchRoster,
    top_alternatives: int = 3,
) -> tuple[LineupRecommendation, list[LineupRecommendation]]:
    """Best 4 personal picks (+ vice fisso se presente nel roster YAML)."""
    vice_player = roster.vice_player()
    vice_ev = compute_player_ev(vice_player) if vice_player else None
    pool = roster.lineup_pool()

    if len(pool) < LINEUP_SIZE:
        raise ValueError(
            f"Sono necessari almeno {LINEUP_SIZE} giocatori oltre al vice "
            f"(presenti {len(pool)})"
        )

    candidates: list[LineupRecommendation] = []
    for combo in itertools.combinations(pool, LINEUP_SIZE):
        if not _valid_lineup(list(combo)):
            continue
        candidates.append(_build_recommendation(combo, vice_ev))

    if not candidates:
        raise ValueError(
            "Nessuna formazione valida: servono giocatori sia home che away "
            f"e almeno {LINEUP_SIZE} totali (escluso vice)"
        )

    candidates.sort(key=lambda c: (-c.ev_total, tuple(c.names)))
    return candidates[0], candidates[1 : 1 + top_alternatives]


def naive_top_scorers_lineup(roster: MatchRoster) -> LineupRecommendation | None:
    """Baseline: top 4 by EV singolo, rispettando vincolo squadra."""
    pool = roster.lineup_pool()
    by_ev = sorted(
        pool,
        key=lambda p: (-compute_player_ev(p).ev_total, p.name.lower()),
    )
    vice_player = roster.vice_player()
    vice_ev = compute_player_ev(vice_player) if vice_player else None

    for combo in itertools.combinations(by_ev, LINEUP_SIZE):
        if _valid_lineup(list(combo)):
            return _build_recommendation(combo, vice_ev)
    return None
