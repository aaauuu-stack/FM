"""Models for K (first sub) and L (first card) event probabilities."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from odds.devig import proportional_devig
from odds.distribution import build_distribution
from odds.goalscorer import estimate_team_expected_goals
from odds.oddspapi_client import fetch_markets_catalog, fetch_odds, oddspapi_configured
from odds.oddspapi_normalize import lookup_oddspapi_fixture
from odds.oddspapi_player_props import extract_player_yes_probs
from odds.scrape_client import fetch_json
from odds.scrape_sofascore import _sofascore_event_id, _sofascore_headers
from odds.scrape_sofascore_players import _choice_decimal
from odds.fast_mode import is_fast_mode
from odds.scrape_sofascore_subs import TeamSubProfile, fetch_team_sub_profile
from players.models import MatchRoster, PlayerBonus
from players.name_match import players_match
from players.team_data import card_prob_from_per90, default_minutes_for_role, get_player_stats

_P_MATCH_CARD = 0.88
_P_MATCH_SUB = 0.98  # almost always at least one sub

_FIRST_CARD_MARKET_HINTS = (
    "first player booked",
    "first player carded",
    "first to be carded",
    "1st player booked",
    "first booking",
)

# Fallback role prior if no history
_ROLE_SUB_PRIOR = {"FWD": 0.22, "MID": 0.16, "DEF": 0.08, "GK": 0.0}


@dataclass
class MatchContext:
    p_home_win: float
    p_draw: float
    p_away_win: float
    lambda_home: float
    lambda_away: float
    expected_total: float


def build_match_context(match) -> MatchContext:
    dist = build_distribution(match)
    sign = dist.sign_probs
    lh, la = estimate_team_expected_goals(match)
    return MatchContext(
        p_home_win=float(sign.get("1", 0.33)),
        p_draw=float(sign.get("X", 0.33)),
        p_away_win=float(sign.get("2", 0.33)),
        lambda_home=lh,
        lambda_away=la,
        expected_total=lh + la,
    )


def _context_sub_multiplier(player: PlayerBonus, ctx: MatchContext) -> float:
    """Adjust sub-off risk from match odds (favorite/underdog, open/closed game)."""
    if player.is_goalkeeper:
        return 0.0

    p_win = ctx.p_home_win if player.side == "home" else ctx.p_away_win
    p_lose = ctx.p_away_win if player.side == "home" else ctx.p_home_win
    role = player.role.upper()
    mult = 1.0

    # Underdog chasing: refresh attackers/mids
    if p_win < 0.32 and role in {"FWD", "MID"}:
        mult *= 1.28
    elif p_win < 0.40 and role == "FWD":
        mult *= 1.15

    # Heavy favorite in low-scoring game: keep defensive shape
    if p_win > 0.58 and ctx.expected_total < 2.3 and role == "DEF":
        mult *= 0.75

    # Open/high-total game: more rotation in attack
    if ctx.expected_total > 2.8 and role in {"FWD", "MID"}:
        mult *= 1.12

    # Key scorer less likely to be first off when team needs goal
    if p_lose > 0.45 and float(player.p_goal or 0) > 0.25:
        mult *= 0.82

    return mult


def _player_historical_sub_weight(
    player: PlayerBonus,
    profile: TeamSubProfile,
) -> float:
    """Combine player + role historical first-sub rates (point 2 + 3)."""
    rate = 0.0
    matched = False
    for name, r in profile.player_first_sub_rate.items():
        if players_match(player.name, name):
            rate = max(rate, r)
            matched = True

    role_rate = profile.role_first_sub_rate.get(player.role.upper(), 0.0)
    if not role_rate:
        role_rate = _ROLE_SUB_PRIOR.get(player.role.upper(), 0.1)

    if matched and profile.sample_matches >= 3:
        return 0.75 * rate + 0.25 * role_rate
    if profile.sample_matches >= 2:
        return 0.4 * rate + 0.6 * role_rate
    return role_rate


def estimate_first_sub_probs(
    roster: MatchRoster,
    match,
) -> tuple[dict[str, float], str]:
    """P(primo sostituito) among starters — storico NT + pattern CT + contesto."""
    ctx = build_match_context(match)
    starters = [p for p in roster.players if p.starter and not p.is_goalkeeper]
    if not starters:
        return {}, "K: nessun titolare"

    profiles: dict[str, TeamSubProfile] = {}
    notes: list[str] = []
    if is_fast_mode():
        profiles = {"home": TeamSubProfile(), "away": TeamSubProfile()}
        notes.append("modalità veloce")
    else:
        for side, team_name, opp in (
            ("home", roster.home, roster.away),
            ("away", roster.away, roster.home),
        ):
            prof = fetch_team_sub_profile(
                team_name,
                roster.kickoff,
                opponent=opp,
            )
            profiles[side] = prof
            if prof.sample_matches:
                notes.append(f"{team_name}: {prof.sample_matches}p")

    weights: dict[str, float] = {}
    for player in starters:
        hist = _player_historical_sub_weight(player, profiles[player.side])
        ctx_m = _context_sub_multiplier(player, ctx)
        p_goal = float(player.p_goal or 0.0)
        # Attaccanti con gol attesi alti leggermente protetti
        protect = 1.0 - min(p_goal, 0.45) * 0.35
        weights[player.name] = max(0.0, hist * ctx_m * protect)

    total = sum(weights.values())
    if total <= 0:
        n = len(starters)
        return {p.name: 1.0 / n for p in starters}, "K: fallback uniforme"

    probs = {name: (w / total) * _P_MATCH_SUB for name, w in weights.items()}
    note = "K: " + (", ".join(notes) if notes else "storico NT non disponibile")
    return probs, note


def _discover_first_card_market_id(catalog: list) -> int | None:
    for market in catalog:
        name = str(market.get("marketName", "")).lower()
        mtype = str(market.get("marketType", "")).lower()
        if "first" in name and ("card" in name or "book" in name):
            return int(market["marketId"])
        if "first" in mtype and "card" in mtype:
            return int(market["marketId"])
    return None


def _extract_first_card_sofa_markets(markets: list) -> dict[str, float]:
    prices: dict[str, list[float]] = {}
    for market in markets:
        name = str(market.get("marketName") or market.get("name") or "").lower()
        if not any(h in name for h in _FIRST_CARD_MARKET_HINTS):
            continue
        for choice in market.get("choices", []):
            label = str(choice.get("name") or choice.get("label") or "").strip()
            if not label or label.lower() in {"yes", "no"}:
                continue
            decimal = _choice_decimal(choice)
            if decimal is None:
                continue
            prices.setdefault(label, []).append(decimal)
    if not prices:
        return {}
    medians = {n: float(statistics.median(v)) for n, v in prices.items()}
    return proportional_devig(medians)


def fetch_first_card_bookmaker_probs(
    roster: MatchRoster,
) -> tuple[dict[str, float], str]:
    """Quote 'first player booked' from OddsPapi + SofaScore (point 6)."""
    probs: dict[str, float] = {}
    notes: list[str] = []

    if oddspapi_configured():
        try:
            catalog = fetch_markets_catalog()
            market_id = _discover_first_card_market_id(catalog)
            if market_id:
                fixture = lookup_oddspapi_fixture(
                    roster.home, roster.away, roster.kickoff
                )
                payload = fetch_odds(str(fixture["fixtureId"]))
                oddspapi_probs = extract_player_yes_probs(payload, market_id)
                if oddspapi_probs:
                    probs.update(oddspapi_probs)
                    notes.append(f"OddsPapi first card ({len(oddspapi_probs)})")
        except (RuntimeError, ValueError):
            pass

    try:
        event_id = _sofascore_event_id(roster.home, roster.away, roster.kickoff)
        if event_id:
            url = f"https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all"
            result = fetch_json(
                url,
                cache_name=f"sofascore_odds_{event_id}.json",
                extra_headers=_sofascore_headers(),
            )
            sofa = _extract_first_card_sofa_markets(result.data.get("markets") or [])
            for name, p in sofa.items():
                if name not in probs:
                    probs[name] = p
            if sofa:
                notes.append(f"SofaScore first card ({len(sofa)})")
    except RuntimeError:
        pass

    return probs, (" | ".join(notes) if notes else "")


def _card_hazard_rate(p_card: float) -> float:
    """Map P(carded in match) to hazard intensity for race-to-first-card."""
    p = min(max(p_card, 0.001), 0.95)
    return -math.log(1.0 - p)


def _card_prob_for_player(player: PlayerBonus, roster: MatchRoster) -> float:
    if player.p_yellow is not None and float(player.p_yellow or 0) > 0:
        return float(player.p_yellow)
    team = roster.home if player.side == "home" else roster.away
    stats = get_player_stats(team, player.name)
    if stats and stats.yellow_per90 > 0:
        minutes = stats.minutes_expected or default_minutes_for_role(player.role)
        return card_prob_from_per90(stats.yellow_per90, minutes)
    return {"GK": 0.04, "DEF": 0.20, "MID": 0.16, "FWD": 0.11}.get(player.role.upper(), 0.12)


def estimate_first_card_probs(
    roster: MatchRoster,
    match,
) -> tuple[dict[str, float], str]:
    """P(primo ammonito) — quote first booked + hazard model su P(cartellino)."""
    pool = [p for p in roster.players if p.starter]
    if not pool:
        return {}, "L: nessun titolare"

    book_probs: dict[str, float] = {}
    book_note = ""
    if not is_fast_mode():
        book_probs, book_note = fetch_first_card_bookmaker_probs(roster)
    matched_book = 0
    hazards: dict[str, float] = {}

    for player in pool:
        for api_name, prob in book_probs.items():
            if players_match(player.name, api_name):
                hazards[player.name] = prob
                matched_book += 1
                break

        if player.name in hazards:
            continue

        p_card = _card_prob_for_player(player, roster)
        if p_card > 0:
            hazards[player.name] = _card_hazard_rate(p_card)

    if not hazards:
        n = len(pool)
        return {p.name: _P_MATCH_CARD / n for p in pool}, "L: fallback uniforme"

    total = sum(hazards.values())
    probs = {name: (h / total) * _P_MATCH_CARD for name, h in hazards.items()}
    note = book_note or "L: hazard da P(cartellino)"
    if matched_book:
        note = f"{note}; book matched={matched_book}"
    return probs, note
