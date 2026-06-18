"""Convert The Odds API events into MatchData."""

from __future__ import annotations

import difflib
import re
import statistics
import unicodedata
from dataclasses import dataclass
from typing import Any

from odds.match_loader import MatchData, MatchOdds

DEFAULT_TOTALS_LINE = 2.5
# Min score (0–1) to accept a team name pair; below → no match.
MIN_TEAM_MATCH_SCORE = 0.72

# Italian app names -> canonical English slug (hint for scoring, not sole source)
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
    "uzbekistan": "uzbekistan",
    "tunisia": "tunisia",
    "egitto": "egypt",
    "algeria": "algeria",
    "norvegia": "norway",
    "svezia": "sweden",
    "sud africa": "south africa",
    "bosnia erzegovina": "bosnia herzegovina",
    "bosnia": "bosnia herzegovina",
    "bosnia and herzegovina": "bosnia herzegovina",
    "costa d avorio": "ivory coast",
    "costa avorio": "ivory coast",
    "capo verde": "cape verde",
    "rd congo": "dr congo",
    "repubblica democratica del congo": "dr congo",
    "congo rd": "dr congo",
    "giordania": "jordan",
    "iraq": "iraq",
    "haiti": "haiti",
    "panama": "panama",
    "curacao": "curacao",
    "nuova zelanda": "new zealand",
    "irlanda": "ireland",
    "scozia": "scotland",
    "grecia": "greece",
    "islanda": "iceland",
    "finlandia": "finland",
    "israele": "israel",
    "cina": "china",
    "thailandia": "thailand",
    "vietnam": "vietnam",
    "indonesia": "indonesia",
    "malesia": "malaysia",
    "filippine": "philippines",
}

# Spelling variants after token split (IT app vs EN API)
_WORD_ALIASES: dict[str, str] = {
    "erzegovina": "herzegovina",
    "ivoire": "ivory",
}


def normalize_team(name: str) -> str:
    """Lowercase ASCII slug for fuzzy matching."""
    text = unicodedata.normalize("NFKD", name.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[-–—/&]", " ", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = TEAM_ALIASES.get(text, text)
    if text:
        words = [_WORD_ALIASES.get(word, word) for word in text.split()]
        text = " ".join(words)
        text = TEAM_ALIASES.get(text, text)
    return text


def _token_set(name: str) -> set[str]:
    norm = normalize_team(name)
    return {token for token in norm.split() if token}


def _token_jaccard(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _sequence_ratio(a: str, b: str) -> float:
    na, nb = normalize_team(a), normalize_team(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def team_match_score(query: str, candidate: str) -> float:
    """
    Similarity 0–1 between a roster/OCR name and an API team name.

    Uses alias normalization + token overlap + character similarity.
    Never uses naive substring (avoids usa ⊂ australia false positives).
    """
    q = normalize_team(query)
    c = normalize_team(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0

    qt, ct = _token_set(query), _token_set(candidate)
    scores: list[float] = [_sequence_ratio(query, candidate), _token_jaccard(query, candidate)]

    if qt and ct:
        if qt <= ct or ct <= qt:
            scores.append(0.95)
        overlap = qt & ct
        if overlap:
            scores.append(len(overlap) / max(len(qt), len(ct)))

    return max(scores)


def teams_match(query: str, api_name: str, *, min_score: float = MIN_TEAM_MATCH_SCORE) -> bool:
    """Return True if query matches API team name with sufficient confidence."""
    return team_match_score(query, api_name) >= min_score


def _fixture_pair_score(
    home_query: str,
    away_query: str,
    event_home: str,
    event_away: str,
) -> float:
    """Score how well a fixture matches queries (both orientations)."""
    direct = min(
        team_match_score(home_query, event_home),
        team_match_score(away_query, event_away),
    )
    swapped = min(
        team_match_score(home_query, event_away),
        team_match_score(away_query, event_home),
    )
    return max(direct, swapped)


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
    *,
    min_score: float = MIN_TEAM_MATCH_SCORE,
) -> dict[str, Any]:
    """
    Find the best-matching event by scoring all fixtures from the API listing.

    Safer than exact string match: handles IT/EN names, hyphens, typos, swapped order.
    """
    if not events:
        raise ValueError(f"Match not found: {home_query} vs {away_query}. Available: (none)")

    ranked: list[tuple[float, dict[str, Any]]] = []
    for event in events:
        home = str(event.get("home_team", ""))
        away = str(event.get("away_team", ""))
        score = _fixture_pair_score(home_query, away_query, home, away)
        ranked.append((score, event))

    ranked.sort(key=lambda item: item[0], reverse=True)
    best_score, best_event = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0

    if best_score < min_score:
        available = [f"{e.get('home_team')} vs {e.get('away_team')}" for e in events]
        raise ValueError(
            f"Match not found: {home_query} vs {away_query} "
            f"(best score {best_score:.2f}, need {min_score:.2f}). "
            f"Available: {', '.join(available)}"
        )

    if second_score >= min_score and (best_score - second_score) < 0.04:
        a = f"{ranked[0][1].get('home_team')} vs {ranked[0][1].get('away_team')}"
        b = f"{ranked[1][1].get('home_team')} vs {ranked[1][1].get('away_team')}"
        raise ValueError(
            f"Match ambiguo per {home_query} vs {away_query}: "
            f"«{a}» ({best_score:.2f}) vs «{b}» ({second_score:.2f}). "
            "Verifica i nomi squadra negli screenshot."
        )

    return best_event


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
