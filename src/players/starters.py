"""Infer likely starters — FM lists full squad; we use SofaScore + heuristic XI."""

from __future__ import annotations

from dataclasses import replace

from odds.scrape_sofascore_subs import fetch_event_gk_starter_names, fetch_event_starter_names
from odds.sofascore_event_lookup import min_sofa_xi_per_side
from players.lineup_web_search import fetch_lineups_web_search
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match
from players.roster_normalize import harmonize_goalkeeper_bonuses

# Portiere titolare: solo SofaScore (posizione G/GK). Mai euristica/book.
_ROLE_SLOTS: dict[str, int] = {"DEF": 4, "MID": 4, "FWD": 2}


def _matches_any(fm_name: str, api_names: set[str]) -> bool:
    return any(players_match(fm_name, name) for name in api_names)


def mark_gk_goalscorer_quotes(
    roster: MatchRoster,
    *prob_sources: dict[str, float] | None,
) -> MatchRoster:
    """
    Mark GK names found in anytime goalscorer markets (for P(gol) / malus only).

    Does NOT determine titolarità — starting GK comes from SofaScore only.
    """
    merged: dict[str, float] = {}
    for src in prob_sources:
        if src:
            merged.update(src)
    if not merged:
        return roster
    updated: list[PlayerBonus] = []
    for player in roster.players:
        if not player.is_goalkeeper:
            updated.append(player)
            continue
        quoted = any(players_match(player.name, api_name) for api_name in merged)
        if quoted:
            updated.append(replace(player, book_goal_matched=True))
        else:
            updated.append(player)
    roster.players = updated
    return roster


def _apply_sofa_gk_starters(
    players: list[PlayerBonus],
    *,
    sofa_gk_home: set[str],
    sofa_gk_away: set[str],
) -> list[str]:
    """
    Mark exactly one GK per side from SofaScore lineups (position G/GK).

    If SofaScore has no GK for a side, no keeper is titolare — no clean-sheet EV.
    """
    notes: list[str] = []
    for side, sofa_gk in (("home", sofa_gk_home), ("away", sofa_gk_away)):
        gks = [p for p in players if p.is_goalkeeper and p.side == side]
        if not gks:
            continue
        for i, player in enumerate(players):
            if player.is_goalkeeper and player.side == side:
                players[i] = replace(player, starter=False)
        if not sofa_gk:
            notes.append(f"portiere {side}: SofaScore non disponibile (nessun EV GK)")
            continue
        matched = [p for p in gks if _matches_any(p.name, sofa_gk)]
        if len(matched) == 1:
            pick = matched[0]
            for i, player in enumerate(players):
                if player.is_goalkeeper and player.side == side:
                    players[i] = replace(
                        player,
                        starter=player.name == pick.name,
                    )
            notes.append(f"portiere {side}: {pick.name} (SofaScore)")
        elif len(matched) > 1:
            notes.append(f"portiere {side}: ambiguo SofaScore ({len(matched)} GK)")
        else:
            names = ", ".join(sorted(sofa_gk)[:3])
            notes.append(f"portiere {side}: {names} non in rosa FM")
    return notes


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
        if player.is_goalkeeper:
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

    Portiere: solo SofaScore (probabili/ufficiali, posizione G).
    Campo: SofaScore → ricerca web → euristica bonus FM.
    """
    updated, note, _, _, _ = infer_starters_impl(
        roster, sofascore_event_id=sofascore_event_id
    )
    return updated, note


def infer_starters_impl(
    roster: MatchRoster,
    *,
    sofascore_event_id: int | None = None,
) -> tuple[MatchRoster, str, set[str], set[str], dict[tuple[str, str], tuple[int, int]]]:
    players = harmonize_goalkeeper_bonuses([replace(p, starter=False) for p in roster.players])
    raw_gk_bonuses = {
        (p.side, p.name): (p.bonus_goal, p.bonus_clean_sheet)
        for p in roster.players
        if p.is_goalkeeper
    }
    notes: list[str] = []
    min_xi = min_sofa_xi_per_side()

    home_names: set[str] = set()
    away_names: set[str] = set()
    sofa_gk_home: set[str] = set()
    sofa_gk_away: set[str] = set()
    lineup_detail = ""
    if sofascore_event_id:
        home_names, away_names, lineup_detail = fetch_event_starter_names(sofascore_event_id)
        sofa_gk_home, sofa_gk_away = fetch_event_gk_starter_names(sofascore_event_id)
        home_names -= {p.name for p in players if p.is_goalkeeper and p.side == "home"}
        away_names -= {p.name for p in players if p.is_goalkeeper and p.side == "away"}

    sofa_home_full = len(home_names) >= min_xi
    sofa_away_full = len(away_names) >= min_xi

    web_home: set[str] = set()
    web_away: set[str] = set()
    web_note = ""
    if not sofa_home_full or not sofa_away_full:
        web_home, web_away, web_note = fetch_lineups_web_search(
            MatchRoster(
                match_id=roster.match_id,
                home=roster.home,
                away=roster.away,
                kickoff=roster.kickoff,
                players=players,
            )
        )
        if web_home and not sofa_home_full:
            home_names = web_home
        elif web_home:
            home_names |= web_home
        if web_away and not sofa_away_full:
            away_names = web_away
        elif web_away:
            away_names |= web_away

    _mark_sofa_starters(players, home_names, away_names)

    if sofa_home_full and sofa_away_full:
        notes.append(f"SofaScore formazioni ({len(home_names)}/{len(away_names)} titolari)")
    elif web_note and (web_home or web_away):
        notes.append(web_note)
    elif home_names or away_names:
        notes.append("SofaScore parziale")
    elif sofascore_event_id and lineup_detail:
        notes.append(lineup_detail)
    else:
        notes.append("SofaScore non disponibile")

    for side in ("home", "away"):
        side_names = home_names if side == "home" else away_names
        if len(side_names) >= min_xi:
            continue
        marked = sum(1 for p in players if p.side == side and p.starter)
        if marked >= min_xi:
            continue
        side_players = [p for p in players if p.side == side]
        xi_names = _heuristic_xi(side_players)
        for i, player in enumerate(players):
            if player.side == side and player.name in xi_names:
                players[i] = replace(player, starter=True)
        if marked < min_xi:
            notes.append(f"euristica bonus FM ({side})")

    notes.extend(
        _apply_sofa_gk_starters(
            players,
            sofa_gk_home=sofa_gk_home,
            sofa_gk_away=sofa_gk_away,
        )
    )

    return (
        MatchRoster(
            match_id=roster.match_id,
            home=roster.home,
            away=roster.away,
            kickoff=roster.kickoff,
            players=players,
        ),
        "; ".join(notes),
        sofa_gk_home,
        sofa_gk_away,
        raw_gk_bonuses,
    )


def resolve_goalkeepers(
    roster: MatchRoster,
    *,
    sofa_gk_home: set[str] | None = None,
    sofa_gk_away: set[str] | None = None,
    raw_gk_bonuses: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> tuple[MatchRoster, str]:
    """Re-apply SofaScore GK titolari (ignora raw_gk_bonuses — kept for API compat)."""
    del raw_gk_bonuses
    players = list(roster.players)
    notes = _apply_sofa_gk_starters(
        players,
        sofa_gk_home=sofa_gk_home or set(),
        sofa_gk_away=sofa_gk_away or set(),
    )
    roster.players = players
    return roster, "; ".join(notes)


def apply_starter_probabilities(roster: MatchRoster) -> MatchRoster:
    """
    Zero event probabilities for non-starters.

    Book quotes are applied before this step but FM awards no points to bench
    players who never enter the pitch — titolarità (SofaScore) gates effective P.
    """
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
