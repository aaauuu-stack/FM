"""Infer likely starters — FM lists full squad; we use SofaScore + heuristic XI."""

from __future__ import annotations

from dataclasses import replace

from odds.scrape_sofascore_subs import fetch_event_starter_names
from odds.sofascore_event_lookup import min_sofa_xi_per_side
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match

# Typical NT shape when we must guess (no lineups / sparse quotes)
_ROLE_SLOTS: dict[str, int] = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}


def _matches_any(fm_name: str, api_names: set[str]) -> bool:
    return any(players_match(fm_name, name) for name in api_names)


def _pick_one_gk(gks: list[PlayerBonus]) -> PlayerBonus | None:
    if not gks:
        return None
    starters = [p for p in gks if p.starter]
    pool = starters if starters else gks
    # FM: bonus più basso ≈ titolare; backup spesso ha quota anytime gol → ultimo criterio
    return min(
        pool,
        key=lambda p: (
            p.bonus_goal,
            p.bonus_clean_sheet,
            int(p.book_goal_matched),
            p.name.lower(),
        ),
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
        if role == "GK":
            pick = _pick_one_gk(pool)
            if pick:
                chosen.add(pick.name)
            continue
        pool.sort(key=lambda p: p.bonus_goal)
        for player in pool[:need]:
            chosen.add(player.name)
    return chosen


def _mark_sofa_starters(
    players: list[PlayerBonus],
    home_names: set[str],
    away_names: set[str],
) -> None:
    for i, player in enumerate(players):
        if player.vice_allenatore:
            players[i] = replace(player, starter=True)
            continue
        side_names = home_names if player.side == "home" else away_names
        if side_names and _matches_any(player.name, side_names):
            players[i] = replace(player, starter=True)


def infer_starters(
    roster: MatchRoster,
    *,
    sofascore_event_id: int | None = None,
) -> tuple[MatchRoster, str]:
    """
    Mark starter=True for expected XI.

    Sources (in order):
    1. SofaScore predicted/confirmed lineups for this fixture
    2. Heuristic XI by role + FM bonus — only if SofaScore missing/incomplete for that side
    Vice allenatore is always treated as starter.
    """
    players = [replace(p, starter=False) for p in roster.players]
    notes: list[str] = []
    min_xi = min_sofa_xi_per_side()

    home_names: set[str] = set()
    away_names: set[str] = set()
    lineup_detail = ""
    if sofascore_event_id:
        home_names, away_names, lineup_detail = fetch_event_starter_names(sofascore_event_id)

    _mark_sofa_starters(players, home_names, away_names)

    home_sofa_ok = len(home_names) >= min_xi
    away_sofa_ok = len(away_names) >= min_xi

    if home_sofa_ok and away_sofa_ok:
        notes.append(f"SofaScore formazioni ({len(home_names)}/{len(away_names)} titolari)")
    elif home_names or away_names:
        notes.append("SofaScore parziale + euristica")
        for side, sofa_ok, side_names in (
            ("home", home_sofa_ok, home_names),
            ("away", away_sofa_ok, away_names),
        ):
            if sofa_ok:
                continue
            side_players = [p for p in players if p.side == side]
            xi_names = _heuristic_xi(side_players)
            for i, player in enumerate(players):
                if player.side == side and player.name in xi_names:
                    players[i] = replace(player, starter=True)
    else:
        if sofascore_event_id and lineup_detail:
            notes.append(lineup_detail + " → euristica")
        else:
            notes.append("euristica ruolo+bonus FM (SofaScore non disponibile)")
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
    """
    Zero event probabilities for non-starters without book quotes.

    Bookmaker P(gol)/P(cartellino) embeds expected minutes for outfielders only.
    Portieri: solo il titolare conserva probabilità (CS da quote partita).
    """
    updated: list[PlayerBonus] = []
    for player in roster.players:
        if player.is_goalkeeper:
            if player.starter:
                updated.append(player)
            else:
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
            continue
        if player.starter or player.book_quote_trusts_minutes:
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
