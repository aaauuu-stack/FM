"""Resolve SofaScore event id for a fixture (OddsPapi id or calendar search)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from odds.api_normalize import teams_match
from odds.scrape_client import fetch_json
from odds.scrape_sofascore import _sofascore_headers

_MIN_SOFA_XI = 10


def min_sofa_xi_per_side() -> int:
    return _MIN_SOFA_XI


def _kickoff_dates(kickoff_iso: str | None) -> list[str]:
    if not kickoff_iso or len(kickoff_iso) < 10:
        return []
    try:
        raw = kickoff_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        day = dt.date()
        return [
            day.isoformat(),
            (day - timedelta(days=1)).isoformat(),
            (day + timedelta(days=1)).isoformat(),
        ]
    except ValueError:
        return [kickoff_iso[:10]]


def _event_matches(event: dict, home_query: str, away_query: str) -> bool:
    ev = event.get("event") if isinstance(event.get("event"), dict) else event
    home_team = ev.get("homeTeam") or {}
    away_team = ev.get("awayTeam") or {}
    home_name = str(home_team.get("name") or home_team.get("shortName") or "")
    away_name = str(away_team.get("name") or away_team.get("shortName") or "")
    if not home_name or not away_name:
        return False
    normal = teams_match(home_query, home_name) and teams_match(away_query, away_name)
    swapped = teams_match(home_query, away_name) and teams_match(away_query, home_name)
    return normal or swapped


def _event_id_from_payload(event: dict) -> int | None:
    ev = event.get("event") if isinstance(event.get("event"), dict) else event
    try:
        eid = int(ev.get("id") or 0)
        return eid or None
    except (TypeError, ValueError):
        return None


def _lookup_scheduled_events(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None,
) -> int | None:
    seen_dates: set[str] = set()
    for date_str in _kickoff_dates(kickoff_iso):
        if date_str in seen_dates:
            continue
        seen_dates.add(date_str)
        url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date_str}"
        try:
            result = fetch_json(
                url,
                cache_name=f"sofascore_scheduled_{date_str}.json",
                extra_headers=_sofascore_headers(),
            )
        except RuntimeError:
            continue
        for event in result.data.get("events") or []:
            if _event_matches(event, home_query, away_query):
                eid = _event_id_from_payload(event)
                if eid:
                    return eid
    return None


def _fetch_team_id_by_name(team_query: str) -> int | None:
    from odds.scrape_sofascore_subs import _fetch_team_id_by_name as _lookup

    return _lookup(team_query)


def _fetch_team_next_events(team_id: int, pages: int = 2) -> list[dict]:
    events: list[dict] = []
    for page in range(pages):
        url = f"https://api.sofascore.com/api/v1/team/{team_id}/events/next/{page}"
        try:
            result = fetch_json(
                url,
                cache_name=f"sofascore_team_next_{team_id}_p{page}.json",
                extra_headers=_sofascore_headers(),
            )
        except RuntimeError:
            break
        batch = result.data.get("events") or []
        if not batch:
            break
        events.extend(batch)
    return events


def _lookup_team_next_events(
    home_query: str,
    away_query: str,
) -> int | None:
    for team_query in (home_query, away_query):
        team_id = _fetch_team_id_by_name(team_query)
        if not team_id:
            continue
        for event in _fetch_team_next_events(team_id):
            if _event_matches(event, home_query, away_query):
                eid = _event_id_from_payload(event)
                if eid:
                    return eid
    return None


def lookup_sofascore_event_id(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
) -> int | None:
    """
    SofaScore event id: OddsPapi sofascoreId, then calendario giorno partita, then next events.
    """
    from odds.sofascore_bundle import sofascore_event_id_from_oddspapi

    eid = sofascore_event_id_from_oddspapi(home_query, away_query, kickoff_iso)
    if eid:
        return eid
    eid = _lookup_scheduled_events(home_query, away_query, kickoff_iso)
    if eid:
        return eid
    return _lookup_team_next_events(home_query, away_query)
