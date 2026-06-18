"""SofaScore scrape: historical first-substitution rates per national team."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from odds.api_normalize import teams_match
from odds.scrape_client import fetch_json
from odds.sofascore_bundle import sofascore_event_id_from_oddspapi
from odds.scrape_sofascore import _sofascore_headers
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

    seen: set[str] = set()
    candidates: list[str] = []
    for raw in (team_query, normalize_team(team_query)):
        slug = raw.replace(" ", "-")
        for q in (raw, slug):
            if q and q not in seen:
                seen.add(q)
                candidates.append(q)

    for query in candidates:
        url = f"https://api.sofascore.com/api/v1/team/search?q={query}"
        try:
            result = fetch_json(
                url,
                cache_name=f"sofascore_team_search_{query}.json",
                extra_headers=_sofascore_headers(),
            )
        except RuntimeError:
            continue

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
        event_id = sofascore_event_id_from_oddspapi(team_query, opponent, kickoff_iso)
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


def fetch_event_starter_names(event_id: int) -> tuple[set[str], set[str], str]:
    """Starter names from SofaScore lineups (predicted or confirmed)."""
    lineups, detail = _fetch_lineups_with_detail(event_id)
    if not lineups:
        return set(), set(), detail
    return (
        _starters_from_lineups(lineups, "home"),
        _starters_from_lineups(lineups, "away"),
        detail,
    )


def _fetch_lineups_with_detail(event_id: int) -> tuple[dict | None, str]:
    lineups = _fetch_lineups(event_id)
    if not lineups:
        return None, "lineups SofaScore non disponibili (HTTP/403 o partita non trovata)"
    home_n = len(_starters_from_lineups(lineups, "home"))
    away_n = len(_starters_from_lineups(lineups, "away"))
    if home_n >= min_sofa_xi_per_side() and away_n >= min_sofa_xi_per_side():
        return lineups, f"lineups SofaScore ({home_n}+{away_n} titolari)"
    if home_n or away_n:
        return lineups, f"lineups SofaScore parziali ({home_n}+{away_n})"
    return lineups, "lineups SofaScore vuote (probabili solo su web, non in API)"


def min_sofa_xi_per_side() -> int:
    from odds.sofascore_event_lookup import min_sofa_xi_per_side as _min

    return _min()


def _sofascore_player_name_variants(player: dict) -> set[str]:
    """All name forms useful to match FM roster (Kobel ↔ G. Kobel)."""
    names: set[str] = set()
    for key in ("name", "shortName"):
        raw = str(player.get(key) or "").strip()
        if raw:
            names.add(raw)
            parts = raw.replace(".", " ").split()
            if parts:
                names.add(parts[-1])
    return names


def _starters_from_lineups(lineups: dict, side_key: str) -> set[str]:
    side = lineups.get(side_key) or {}
    players_list = side.get("players") or []
    if not players_list:
        return set()

    names: set[str] = set()
    has_sub_flag = any(
        isinstance(entry, dict) and "substitute" in entry for entry in players_list
    )

    if has_sub_flag:
        for entry in players_list:
            if not isinstance(entry, dict) or entry.get("substitute") is True:
                continue
            player = entry.get("player") or {}
            names.update(_sofascore_player_name_variants(player))
    else:
        for entry in players_list[:11]:
            if not isinstance(entry, dict):
                continue
            player = entry.get("player") or {}
            names.update(_sofascore_player_name_variants(player))
    return names


def _fetch_predicted_lineups(event_id: int) -> dict | None:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}/predicted-lineups"
    try:
        result = fetch_json(
            url,
            cache_name=f"sofascore_predicted_lineups_{event_id}.json",
            extra_headers=_sofascore_headers(),
        )
        data = result.data
        if data.get("home") or data.get("away"):
            return data
    except RuntimeError:
        pass
    return None


def _fetch_lineups(event_id: int) -> dict | None:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}/lineups"
    try:
        result = fetch_json(
            url,
            cache_name=f"sofascore_lineups_{event_id}.json",
            extra_headers=_sofascore_headers(),
        )
        data = result.data
        home = (data.get("home") or {}).get("players") or []
        away = (data.get("away") or {}).get("players") or []
        if home or away:
            return data
    except RuntimeError:
        pass
    return _fetch_predicted_lineups(event_id)


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


def _process_historical_event(
    event: dict,
    team_id: int,
) -> tuple[int, dict[str, int], dict[str, int], dict[str, int], dict[str, int]] | None:
    """Fetch lineups+incidents for one past match; return counts or None."""
    event_id = int(event.get("id") or 0)
    if not event_id:
        return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        lineups_f = pool.submit(_fetch_lineups, event_id)
        incidents_f = pool.submit(_fetch_incidents, event_id)
        lineups = lineups_f.result()
        incidents = incidents_f.result()

    if not lineups:
        return None

    home_id = int((event.get("homeTeam") or {}).get("id") or 0)
    side_key = "home" if home_id == team_id else "away"
    starters = _starters_from_lineups(lineups, side_key)
    if not starters:
        return None

    first_out = _first_sub_out_by_side(incidents).get(side_key)
    if not first_out:
        return None

    first_sub_counts: dict[str, int] = {}
    starter_counts: dict[str, int] = {}
    role_first: dict[str, int] = {}
    role_starter: dict[str, int] = {}

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

    return 1, first_sub_counts, starter_counts, role_first, role_starter


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

    workers = min(6, max(1, len(finished)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(
            lambda ev: _process_historical_event(ev, team_id),
            finished,
        ):
            if result is None:
                continue
            n, fs, sc, rf, rs = result
            used += n
            for k, v in fs.items():
                first_sub_counts[k] = first_sub_counts.get(k, 0) + v
            for k, v in sc.items():
                starter_counts[k] = starter_counts.get(k, 0) + v
            for k, v in rf.items():
                role_first[k] = role_first.get(k, 0) + v
            for k, v in rs.items():
                role_starter[k] = role_starter.get(k, 0) + v

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
