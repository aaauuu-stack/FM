"""Single SofaScore event fetch — CS, player props, first card, team ids."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from odds.match_loader import MatchOdds
from odds.scrape_sofascore import (
    _extract_ht_markets,
    _extract_ft_markets,
    _sofascore_event_id,
    _sofascore_headers,
)
from odds.scrape_client import fetch_json
from odds.scrape_sofascore_players import (
    extract_card_probs_from_sofa_markets,
    extract_goalscorer_from_sofa_markets,
    fetch_sofascore_team_player_stats,
)
from odds.event_kl_model import _extract_first_card_sofa_markets


@dataclass
class SofaScoreBundle:
    match_odds: MatchOdds | None = None
    goal_probs: dict[str, float] | None = None
    card_probs: dict[str, float] | None = None
    stats: dict | None = None
    props_note: str = ""
    first_card_probs: dict[str, float] | None = None
    first_card_note: str = ""
    event_id: int | None = None


def _fetch_event_teams(event_id: int) -> tuple[int, int] | None:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}"
    result = fetch_json(
        url,
        cache_name=f"sofascore_event_{event_id}.json",
        extra_headers=_sofascore_headers(),
    )
    event = result.data.get("event") or result.data
    home_id = int((event.get("homeTeam") or {}).get("id") or 0)
    away_id = int((event.get("awayTeam") or {}).get("id") or 0)
    if home_id and away_id:
        return home_id, away_id
    return None


def fetch_sofascore_bundle(
    home_query: str,
    away_query: str,
    kickoff_iso: str | None = None,
    *,
    need_match_cs: bool = True,
    need_props: bool = True,
    need_first_card: bool = True,
) -> SofaScoreBundle:
    """One event id + odds payload for all SofaScore scrape paths."""
    bundle = SofaScoreBundle()
    event_id = _sofascore_event_id(home_query, away_query, kickoff_iso)
    if event_id is None:
        bundle.props_note = "SofaScore: evento non trovato"
        return bundle

    bundle.event_id = event_id
    odds_url = f"https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all"
    odds_result = fetch_json(
        odds_url,
        cache_name=f"sofascore_odds_{event_id}.json",
        extra_headers=_sofascore_headers(),
    )
    markets = odds_result.data.get("markets") or []

    if need_match_cs and markets:
        ft = _extract_ft_markets(markets)
        ht = _extract_ht_markets(markets)
        if ft or ht:
            bundle.match_odds = MatchOdds(correct_score=ft, half_time_correct_score=ht)

    notes: list[str] = []
    if need_props:
        goal_probs = extract_goalscorer_from_sofa_markets(markets) if markets else {}
        card_probs = extract_card_probs_from_sofa_markets(markets) if markets else {}
        stats: dict = {}
        try:
            teams = _fetch_event_teams(event_id)
            if teams:
                home_id, away_id = teams
                with ThreadPoolExecutor(max_workers=2) as pool:
                    f_home = pool.submit(fetch_sofascore_team_player_stats, home_id)
                    f_away = pool.submit(fetch_sofascore_team_player_stats, away_id)
                    stats.update(f_home.result())
                    stats.update(f_away.result())
                if stats:
                    notes.append(f"stats NT {len(stats)} giocatori")
        except RuntimeError as exc:
            notes.append(f"stats: {exc}")

        if goal_probs:
            notes.append(f"quote gol {len(goal_probs)}")
        if card_probs:
            notes.append(f"quote cartellini {len(card_probs)}")
        bundle.goal_probs = goal_probs
        bundle.card_probs = card_probs
        bundle.stats = stats
        bundle.props_note = (
            "SofaScore scrape (" + ", ".join(notes) + ")" if notes else "SofaScore: nessun dato"
        )

    if need_first_card and markets:
        sofa_fc = _extract_first_card_sofa_markets(markets)
        if sofa_fc:
            bundle.first_card_probs = sofa_fc
            bundle.first_card_note = f"SofaScore first card ({len(sofa_fc)})"

    return bundle
