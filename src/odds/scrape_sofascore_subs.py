"""SofaScore scrape: historical first-substitution rates per national team."""

from __future__ import annotations

from dataclasses import dataclass, field

from odds.api_normalize import teams_match
from odds.scrape_client import fetch_json
from odds.scrape_sofascore import _sofascore_event_id, _sofascore_headers
from players.name_match import players_match

DEFAULT_HISTORY_MATCHES = 10


@dataclass
class TeamSubProfile:
    player_first_sub_rate: dict[str, float] = field(default_factory=dict)
    role_first_sub_rate: dict[str, float] = field(default_factory=dict)
    sample_matches: int = 0
    source: str = "none"


def _fetch_team_id_by_name(team_query: str) -> int | None:
    from odds.api_normalize import normalize_team

    slug = normalize_team(team_query).replace(" ", "-")
    url = f"https://api.sofascore.com/api/v1/team/search?q={slug}"
    try:
        result = fetch_json(
            url,
            cache_name=f"sofascore_team_search_{slug}.json",
            extra_headers=_sofascore_headers(),
        )
    except RuntimeError:
        return None

    teams = result.data.get("teams") or []
    for entry in teams:
        team = entry.get("team") or entry
        name = str(team.get("name") or "")
        if teams_match(team_query, name):
            tid = int(team.get("id") or 0)
            if tid:
                return tid
    if teams:
        team = teams[0].get("team") or teams[0]
        return int(team.get("id") or 0) or None
    return None


def resolve_team_id(
    team_query: str,
    kickoff_iso: str | None = None,
    *,
    opponent: str | None = None,
) -> int | None:
    if opponent:
        event_id = _sofascore_event_id(team_query, opponent, kickoff_iso)
        if event_id:
            url = f"https://api.sofascore.com/api/v1/event/{event_id}"
            try:
                result = fetch_json(
                    url,
                    cache_name=f"sofascore_event_{event_id}.json",
                    extra_headers=_sofascore_headers(),
                )
                event = result.data.get("event") or result.data
                for key in ("homeTeam", "awayTeam"):
                    team = event.get(key) or {}
                    if teams_match(team_query, str(team.get("name") or "")):
                        tid = int(team.get("id") or 0)
                        if tid:
                            return tid
            except RuntimeError:
                pass
    return _fetch_team_id_by_name(team_query)


def _fetch_team_recent_events(team_id: int, pages: int = 1) -> list[dict]:
    events: list[dict] = []
    for page in range(pages):
        url = f"https://api.sofascore.com/api/v1/team/{team_id}/events/last/{page}"
        try:
            result = fetch_json(
                url,
                cache_name=f"sofascore_team_events_{team_id}_p{page}.json",
                extra_headers=_sofascore_headers(),
            )
        except RuntimeError:
            break
        batch = result.data.get("events") or []
        if not batch:
            break
        events.extend(batch)
    return events


def _fetch_lineups(event_id: int) -> dict | None:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}/lineups"
    try:
        result = fetch_json(
            url,
            cache_name=f"sofascore_lineups_{event_id}.json",
            extra_headers=_sofascore_headers(),
        )
        return result.data
    except RuntimeError:
        return None


def _fetch_incidents(event_id: int) -> list[dict]:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}/incidents"
    try:
        result = fetch_json(
            url,
            cache_name=f"sofascore_incidents_{event_id}.json",
            extra_headers=_sofascore_headers(),
        )
        return result.data.get("incidents") or []
    except RuntimeError:
        return []


def _starters_from_lineups(lineups: dict, side_key: str) -> set[str]:
    side = lineups.get(side_key) or {}
    names: set[str] = set()
    for entry in side.get("players") or []:
        if not isinstance(entry, dict) or entry.get("substitute") is True:
            continue
        player = entry.get("player") or {}
        name = str(player.get("name") or player.get("shortName") or "").strip()
        if name:
            names.add(name)
    return names


def _first_sub_out_by_side(incidents: list[dict]) -> dict[str, str | None]:
    found: dict[str, str | None] = {"home": None, "away": None}
    sorted_inc = sorted(incidents, key=lambda x: int(x.get("time") or 999))
    for inc in sorted_inc:
        itype = str(inc.get("incidentType") or inc.get("type") or "").lower()
        if "subst" not in itype:
            continue
        side = "home" if inc.get("isHome") else "away"
        if found[side] is not None:
            continue
        player_out = inc.get("playerOut") or inc.get("player") or {}
        name = str(player_out.get("name") or player_out.get("shortName") or "").strip()
        if name:
            found[side] = name
    return found


def _role_from_lineups(lineups: dict, side_key: str, player_name: str) -> str | None:
    side = lineups.get(side_key) or {}
    for entry in side.get("players") or []:
        player = entry.get("player") or {}
        name = str(player.get("name") or player.get("shortName") or "")
        if not players_match(player_name, name):
            continue
        pos = str(entry.get("position") or player.get("position") or "M").upper()
        if pos in {"G", "GK"}:
            return "GK"
        if pos in {"D", "DEF"}:
            return "DEF"
        if pos in {"F", "FWD", "A"}:
            return "FWD"
        return "MID"
    return None


def fetch_team_sub_profile(
    team_query: str,
    kickoff_iso: str | None = None,
    *,
    opponent: str | None = None,
    max_matches: int = DEFAULT_HISTORY_MATCHES,
) -> TeamSubProfile:
    """Build first-sub rates from last NT matches on SofaScore."""
    team_id = resolve_team_id(team_query, kickoff_iso, opponent=opponent)
    if not team_id:
        return TeamSubProfile(source="SofaScore: team id non trovato")

    events = _fetch_team_recent_events(team_id, pages=2)
    finished = [
        e
        for e in events
        if str(e.get("status", {}).get("type", "")).lower() in {"finished", "closed"}
    ][:max_matches]

    first_sub_counts: dict[str, int] = {}
    starter_counts: dict[str, int] = {}
    role_first: dict[str, int] = {}
    role_starter: dict[str, int] = {}
    used = 0

    for event in finished:
        event_id = int(event.get("id") or 0)
        if not event_id:
            continue
        lineups = _fetch_lineups(event_id)
        if not lineups:
            continue

        home_id = int((event.get("homeTeam") or {}).get("id") or 0)
        side_key = "home" if home_id == team_id else "away"
        starters = _starters_from_lineups(lineups, side_key)
        if not starters:
            continue

        first_out = _first_sub_out_by_side(_fetch_incidents(event_id)).get(side_key)
        if not first_out:
            continue

        used += 1
        matched = None
        for s in starters:
            starter_counts[s] = starter_counts.get(s, 0) + 1
            if players_match(s, first_out):
                matched = s

        target = matched or first_out
        first_sub_counts[target] = first_sub_counts.get(target, 0) + 1
        role = _role_from_lineups(lineups, side_key, target)
        if role:
            role_first[role] = role_first.get(role, 0) + 1
        for s in starters:
            r = _role_from_lineups(lineups, side_key, s)
            if r:
                role_starter[r] = role_starter.get(r, 0) + 1

    player_rates = {
        name: first_sub_counts.get(name, 0) / max(starter_counts.get(name, 0), 1)
        for name in starter_counts
    }
    role_rates = {
        role: role_first.get(role, 0) / max(role_starter.get(role, 0), 1)
        for role in role_starter
    }

    if not player_rates and not role_rates:
        return TeamSubProfile(source="SofaScore: storico vuoto")

    return TeamSubProfile(
        player_first_sub_rate=player_rates,
        role_first_sub_rate=role_rates,
        sample_matches=used,
        source=f"SofaScore storico ({used} partite)",
    )
