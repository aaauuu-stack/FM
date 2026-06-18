"""Infer likely starters — FM lists full squad; we use SofaScore + heuristic XI."""

from __future__ import annotations

from dataclasses import replace

from odds.scrape_sofascore_subs import fetch_event_starter_names
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match

# Typical NT shape when we must guess (no lineups / sparse quotes)
_ROLE_SLOTS: dict[str, int] = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}


def _matches_any(fm_name: str, api_names: set[str]) -> bool:
    return any(players_match(fm_name, name) for name in api_names)


def _pick_one_gk(gks: list[PlayerBonus]) -> PlayerBonus | None:
    if not gks:
        return None
    return max(
        gks,
        key=lambda p: (p.starter, p.bonus_clean_sheet, -p.bonus_goal),
    )


def _consolidate_gk_starters(players: list[PlayerBonus]) -> None:
    """Exactly one starting GK per side."""
    for side in ("home", "away"):
        gks = [p for p in players if p.is_goalkeeper and p.side == side]
        if not gks:
            continue
        starters = [p for p in gks if p.starter]
        pick = _pick_one_gk(starters if starters else gks)
        if not pick:
            continue
        for p in gks:
            idx = players.index(p)
            players[idx] = replace(
                p,
                starter=(p is pick or p.name == pick.name and p.side == pick.side),
            )


def _heuristic_xi(side_players: list[PlayerBonus]) -> set[str]:
    """Fill up to 11 starters by role when SofaScore lineups are incomplete."""
    chosen: set[str] = set()
    already = {p.name for p in side_players if p.starter}
    chosen.update(already)

    for role, slots in _ROLE_SLOTS.items():
        in_role = [p for p in side_players if p.role.upper() == role]
        current = [p for p in in_role if p.name in chosen]
        need = max(0, slots - len(current))
        if need == 0:
            continue
        pool = [p for p in in_role if p.name not in chosen]
        # Bonus FM basso ≈ titolare probabile (regolamento FM)
        pool.sort(key=lambda p: p.bonus_goal)
        for player in pool[:need]:
            chosen.add(player.name)
    return chosen


def infer_starters(
    roster: MatchRoster,
    *,
    sofascore_event_id: int | None = None,
) -> tuple[MatchRoster, str]:
    """
    Mark starter=True for expected XI.

    Sources (in order):
    1. SofaScore predicted/confirmed lineups for this fixture
    2. Heuristic XI by role + FM bonus (low bonus ≈ more likely starter)
    Vice allenatore is always treated as starter.

    Quote cartellini/gol NON influenzano i titolari — servono solo per EV/malus.
    """
    players = [replace(p, starter=False) for p in roster.players]
    notes: list[str] = []

    home_names: set[str] = set()
    away_names: set[str] = set()
    if sofascore_event_id:
        home_names, away_names = fetch_event_starter_names(sofascore_event_id)
        if home_names or away_names:
            notes.append("SofaScore formazioni")

    for i, player in enumerate(players):
        if player.vice_allenatore:
            players[i] = replace(player, starter=True)
            continue
        side_names = home_names if player.side == "home" else away_names
        if side_names and _matches_any(player.name, side_names):
            players[i] = replace(player, starter=True)

    if not notes:
        notes.append("euristica ruolo+bonus FM")

    for side in ("home", "away"):
        side_players = [p for p in players if p.side == side]
        xi_names = _heuristic_xi(side_players)
        for i, player in enumerate(players):
            if player.side == side and player.name in xi_names:
                players[i] = replace(player, starter=True)

    _consolidate_gk_starters(players)

    return (
        MatchRoster(
            match_id=roster.match_id,
            home=roster.home,
            away=roster.away,
            kickoff=roster.kickoff,
            players=players,
        ),
        "; ".join(notes),
    )


def apply_starter_probabilities(roster: MatchRoster) -> MatchRoster:
    """Zero event probabilities for non-starters (bench cannot score)."""
    updated: list[PlayerBonus] = []
    for player in roster.players:
        if player.starter:
            updated.append(player)
            continue
        updated.append(
            player.with_probs(
                p_goal=0.0,
                p_gk_goal=0.0,
                p_penalty_scored=0.0,
                p_penalty_missed=0.0,
                p_penalty_saved=0.0,
                p_yellow=0.0,
                p_red=0.0,
                p_own_goal=0.0,
                p_clean_sheet=0.0,
            )
        )
    roster.players = updated
    return roster


def resolve_starters(
    roster: MatchRoster,
    *,
    sofascore_event_id: int | None = None,
) -> MatchRoster:
    """Infer starters and return roster only (FM never marks titolari)."""
    updated, _note = infer_starters(roster, sofascore_event_id=sofascore_event_id)
    return updated
