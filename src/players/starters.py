"""Infer likely starters — FM lists full squad; we use SofaScore + heuristic XI."""

from __future__ import annotations

from dataclasses import replace

from odds.scrape_sofascore_subs import fetch_event_gk_starter_names, fetch_event_starter_names
from odds.sofascore_event_lookup import min_sofa_xi_per_side
from players.lineup_web_search import fetch_lineups_web_search
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match
from players.roster_normalize import harmonize_goalkeeper_bonuses

# GK titolari: SofaScore lineups, else bonus FM (più basso = titolare).
_ROLE_SLOTS: dict[str, int] = {"DEF": 4, "MID": 4, "FWD": 2}


def _matches_any(fm_name: str, api_names: set[str]) -> bool:
    return any(players_match(fm_name, name) for name in api_names)


def _pick_one_gk(gks: list[PlayerBonus]) -> PlayerBonus | None:
    """
    Choose the likely starting GK from the full squad list.

    FM: lower bonus_goal / bonus_clean_sheet ≈ titolare.
    Backup GKs often appear in the anytime goalscorer market (book_goal_matched).
    """
    if not gks:
        return None
    return min(
        gks,
        key=lambda p: (
            p.bonus_goal,
            p.bonus_clean_sheet,
            int(p.book_goal_matched),
            int(p.book_card_matched),
            p.name.lower(),
        ),
    )


def _pick_gk_for_side(
    gks: list[PlayerBonus],
    sofa_gk_names: set[str],
) -> PlayerBonus | None:
    """Prefer SofaScore GK when exactly one roster keeper matches."""
    if not gks:
        return None
    if sofa_gk_names:
        matched = [p for p in gks if _matches_any(p.name, sofa_gk_names)]
        if len(matched) == 1:
            return matched[0]
    return _pick_one_gk(gks)


def mark_gk_goalscorer_quotes(
    roster: MatchRoster,
    probs: dict[str, float] | None,
) -> MatchRoster:
    """
    Mark GK names found in the anytime goalscorer market before titolarità pick.

    Books quote backup keepers more often than the #1; used only as a tie-breaker
    after FM bonus, not to assign P(gol) yet.
    """
    if not probs:
        return roster
    updated: list[PlayerBonus] = []
    for player in roster.players:
        if not player.is_goalkeeper:
            updated.append(player)
            continue
        quoted = any(players_match(player.name, api_name) for api_name in probs)
        if quoted:
            updated.append(replace(player, book_goal_matched=True))
        else:
            updated.append(player)
    roster.players = updated
    return roster


def _consolidate_gk_starters(
    players: list[PlayerBonus],
    *,
    sofa_gk_home: set[str] | None = None,
    sofa_gk_away: set[str] | None = None,
) -> list[str]:
    """
    Exactly one starting GK per side.

    SofaScore GK (position G) wins when available; else FM bonus + book quotes
    over the full keeper pool — never only among already-marked names.
    """
    notes: list[str] = []
    sofa_by_side = {
        "home": sofa_gk_home or set(),
        "away": sofa_gk_away or set(),
    }
    for side in ("home", "away"):
        gks = [p for p in players if p.is_goalkeeper and p.side == side]
        if not gks:
            continue
        wrong = [p.name for p in gks if p.starter]
        pick = _pick_gk_for_side(gks, sofa_by_side[side])
        if not pick:
            continue
        for i, player in enumerate(players):
            if player.is_goalkeeper and player.side == side:
                players[i] = replace(
                    player,
                    starter=player.name == pick.name,
                )
        if sofa_by_side[side] and _matches_any(pick.name, sofa_by_side[side]):
            notes.append(f"portiere {side}: {pick.name} (SofaScore)")
        elif wrong and pick.name not in wrong:
            notes.append(f"portiere {side}: {pick.name} (non {wrong[0]})")
        elif not wrong:
            notes.append(f"portiere {side}: {pick.name} (bonus FM)")
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
    2. Web search for probable lineups (when SofaScore missing/incomplete)
    3. Heuristic XI by role + FM bonus — only if both above fail for that side
    Vice allenatore is always treated as starter.
    """
    players = harmonize_goalkeeper_bonuses([replace(p, starter=False) for p in roster.players])
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
        _consolidate_gk_starters(
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
    )


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
