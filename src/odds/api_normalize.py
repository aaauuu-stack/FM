"""Convert The Odds API events into MatchData."""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass
from typing import Any

from odds.match_loader import MatchData, MatchOdds

DEFAULT_TOTALS_LINE = 2.5

# Italian app names -> common English API names (extend as needed)
TEAM_ALIASES: dict[str, str] = {
    "inghilterra": "england",
    "croazia": "croatia",
    "francia": "france",
    "brasile": "brazil",
    "germania": "germany",
    "scozia": "scotland",
    "spagna": "spain",
    "italia": "italy",
    "argentina": "argentina",
    "olanda": "netherlands",
    "paesi bassi": "netherlands",
    "belgio": "belgium",
    "portogallo": "portugal",
    "uruguay": "uruguay",
    "colombia": "colombia",
    "messico": "mexico",
    "usa": "usa",
    "stati uniti": "usa",
    "giappone": "japan",
    "corea del sud": "south korea",
    "australia": "australia",
    "svizzera": "switzerland",
    "danimarca": "denmark",
    "austria": "austria",
    "turchia": "turkey",
    "serbia": "serbia",
    "marocco": "morocco",
    "senegal": "senegal",
    "camerun": "cameroon",
    "ghana": "ghana",
    "nigeria": "nigeria",
    "canada": "canada",
    "ecuador": "ecuador",
    "paraguay": "paraguay",
    "cile": "chile",
    "peru": "peru",
    "costa rica": "costa rica",
    "galles": "wales",
    "irlanda": "ireland",
    "ucraina": "ukraine",
    "polonia": "poland",
    "repubblica ceca": "czech republic",
    "czechia": "czech republic",
    "ungheria": "hungary",
    "romania": "romania",
    "slovacchia": "slovakia",
    "slovenia": "slovenia",
    "albania": "albania",
    "georgia": "georgia",
    "arabia saudita": "saudi arabia",
    "iran": "iran",
    "qatar": "qatar",
    "tunisia": "tunisia",
    "egitto": "egypt",
    "algeria": "algeria",
}


def normalize_team(name: str) -> str:
    """Lowercase ASCII name for fuzzy matching."""
    text = unicodedata.normalize("NFKD", name.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return TEAM_ALIASES.get(text, text)


def teams_match(query: str, api_name: str) -> bool:
    """Return True if query matches API team name."""
    q = normalize_team(query)
    a = normalize_team(api_name)
    if q == a:
        return True
    return q in a or a in q


@dataclass
class ApiEventSummary:
    event_id: str
    home: str
    away: str
    kickoff: str


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _collect_h2h_prices(
    bookmakers: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    market_key: str,
) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = {"home": [], "draw": [], "away": []}

    for book in bookmakers:
        for market in book.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                name = str(outcome.get("name", ""))
                price = float(outcome["price"])
                if teams_match(home_team, name):
                    buckets["home"].append(price)
                elif teams_match(away_team, name):
                    buckets["away"].append(price)
                elif normalize_team(name) == "draw":
                    buckets["draw"].append(price)

    return buckets


def _collect_totals_prices(
    bookmakers: list[dict[str, Any]],
    preferred_line: float = DEFAULT_TOTALS_LINE,
) -> tuple[float, dict[str, list[float]]]:
    """Return chosen line and over/under price lists."""
    by_line: dict[float, dict[str, list[float]]] = {}

    for book in bookmakers:
        for market in book.get("markets", []):
            if market.get("key") != "totals":
                continue
            for outcome in market.get("outcomes", []):
                line = float(outcome.get("point", preferred_line))
                name = str(outcome.get("name", "")).lower()
                price = float(outcome["price"])
                by_line.setdefault(line, {"over": [], "under": []})
                if "over" in name:
                    by_line[line]["over"].append(price)
                elif "under" in name:
                    by_line[line]["under"].append(price)

    if not by_line:
        return preferred_line, {"over": [], "under": []}

    line = min(by_line.keys(), key=lambda x: abs(x - preferred_line))
    return line, by_line[line]


def event_to_match_data(event: dict[str, Any]) -> MatchData:
    """Build MatchData from a single Odds API event object."""
    home = str(event["home_team"])
    away = str(event["away_team"])
    bookmakers = event.get("bookmakers", [])

    h2h = _collect_h2h_prices(bookmakers, home, away, "h2h")
    ht = _collect_h2h_prices(bookmakers, home, away, "h2h_h1")

    if not h2h["home"] or not h2h["draw"] or not h2h["away"]:
        raise ValueError(f"Incomplete h2h odds for {home} vs {away}")

    totals_line, totals = _collect_totals_prices(bookmakers)

    odds = MatchOdds(
        h2h={
            "home": _median(h2h["home"]),
            "draw": _median(h2h["draw"]),
            "away": _median(h2h["away"]),
        },
        totals={"line": totals_line},
        ht_result={},
    )

    if totals["over"] and totals["under"]:
        odds.totals["over"] = _median(totals["over"])
        odds.totals["under"] = _median(totals["under"])

    if ht["home"] and ht["draw"] and ht["away"]:
        odds.ht_result = {
            "home": _median(ht["home"]),
            "draw": _median(ht["draw"]),
            "away": _median(ht["away"]),
        }

    match_id = _build_match_id(home, away)

    return MatchData(
        match_id=match_id,
        home=home,
        away=away,
        kickoff=str(event.get("commence_time", "")),
        odds=odds,
    )


def _build_match_id(home: str, away: str) -> str:
    home_code = normalize_team(home).replace(" ", "")[:3].upper() or "HOM"
    away_code = normalize_team(away).replace(" ", "")[:3].upper() or "AWY"
    return f"{home_code}-{away_code}"


def find_event(
    events: list[dict[str, Any]],
    home_query: str,
    away_query: str,
) -> dict[str, Any]:
    """Find event by home/away team names (IT or EN)."""
    for event in events:
        home = str(event.get("home_team", ""))
        away = str(event.get("away_team", ""))
        if teams_match(home_query, home) and teams_match(away_query, away):
            return event

    available = [f"{e.get('home_team')} vs {e.get('away_team')}" for e in events]
    raise ValueError(
        f"Match not found: {home_query} vs {away_query}. "
        f"Available: {', '.join(available) if available else '(none)'}"
    )


def list_events(events: list[dict[str, Any]]) -> list[ApiEventSummary]:
    summaries: list[ApiEventSummary] = []
    for event in events:
        summaries.append(
            ApiEventSummary(
                event_id=str(event.get("id", "")),
                home=str(event.get("home_team", "")),
                away=str(event.get("away_team", "")),
                kickoff=str(event.get("commence_time", "")),
            )
        )
    return summaries
