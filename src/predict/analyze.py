"""Full match analysis — structured output for CLI and web."""

from __future__ import annotations

from dataclasses import dataclass, field

from odds.goalscorer import attach_all_player_probs, attach_clean_sheet_probs
from odds.scrape_sofascore_subs import TeamSubProfile
from players.models import MatchRoster
from players.roster_loader import load_roster
from players.starters import apply_starter_probabilities, infer_starters
from predict.event_ev import recommend_first_card, recommend_first_sub
from predict.prefetch import build_match_parallel
from predict.ev_report import (
    EvReport,
    event_recommendation_to_report,
    lineup_recommendation_to_report,
    result_recommendation_to_report,
)
from predict.lineup_ev import naive_top_scorers_lineup, optimize_lineup, rank_players
from predict.result_ev import rank_predictions
from scoring.lineup_points import PlayerEv


@dataclass
class MatchAnalysis:
    home: str
    away: str
    source_note: str
    requests_remaining: int | None
    result: EvReport | None
    first_sub: EvReport | None
    first_card: EvReport | None
    lineup: EvReport | None
    lineup_ev: float
    events_ev: float
    vice_name: str | None
    vice_bonus: int | None
    top_players: list[PlayerEv] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _analyze_with_roster(
    roster: MatchRoster,
    *,
    sport: str = "soccer_fifa_world_cup",
    region: str = "eu",
    refresh: bool = False,
    use_oddspapi: bool = True,
    use_scrape: bool = True,
    top_n: int = 5,
) -> MatchAnalysis:
    match, source_note, remaining, _event_id, prefetch = build_match_parallel(
        roster,
        sport=sport,
        region=region,
        refresh=refresh,
        use_oddspapi=use_oddspapi,
        use_scrape=use_scrape,
    )

    dist, ranked = rank_predictions(match, top_n=top_n)
    result_report: EvReport | None = None
    if ranked:
        result_report = result_recommendation_to_report(
            match.home,
            match.away,
            match_id=match.match_id,
            kickoff=match.kickoff,
            source_note=source_note,
            dist=dist,
            best=ranked[0],
            ranked=ranked,
            top_n=top_n,
        )

    roster, starter_note = infer_starters(
        roster,
        sofascore_event_id=prefetch.sofascore_event_id,
    )
    roster, gs_note = attach_all_player_probs(
        roster,
        match,
        sport=sport,
        region=region,
        force_refresh=refresh,
        use_oddspapi=use_oddspapi,
        use_scrape=use_scrape,
        oddspapi_props=prefetch.oddspapi_props if use_oddspapi else None,
        sofa_props=prefetch.sofa_props if use_scrape else None,
        goalscorer_probs=prefetch.goalscorer_probs,
        event_player_props=prefetch.event_player_props,
        starters_only=True,
        starters_only_poisson=True,
    )
    roster = attach_clean_sheet_probs(roster, match)
    roster = apply_starter_probabilities(roster)

    player_note = gs_note
    if starter_note:
        player_note = f"Titolari: {starter_note} | {gs_note}"

    first_card = prefetch.first_card if (use_oddspapi or use_scrape) else None
    book_probs = first_card[0] if first_card else None
    book_note = first_card[1] if first_card else ""

    # Storico NT sostituzioni (K) disabilitato per ora — fallback ruolo + contesto partita
    sub_rec = recommend_first_sub(
        roster,
        match,
        sub_profiles={"home": TeamSubProfile(), "away": TeamSubProfile()},
    )
    card_rec = recommend_first_card(
        roster,
        match,
        book_probs=book_probs,
        book_note=book_note,
    )
    sub_report = event_recommendation_to_report(sub_rec) if sub_rec else None
    card_report = event_recommendation_to_report(card_rec) if card_rec else None

    best, alternatives = optimize_lineup(roster)
    baseline = naive_top_scorers_lineup(roster)
    lineup_report = lineup_recommendation_to_report(
        roster.home,
        roster.away,
        best,
        source_note=player_note,
        alternatives=alternatives,
        baseline=baseline,
    )

    vice = roster.vice_player()
    top_players = rank_players(roster, top_n=8)
    ev_events = (sub_rec.ev if sub_rec else 0.0) + (card_rec.ev if card_rec else 0.0)

    return MatchAnalysis(
        home=match.home,
        away=match.away,
        source_note=source_note,
        requests_remaining=remaining,
        result=result_report,
        first_sub=sub_report,
        first_card=card_report,
        lineup=lineup_report,
        lineup_ev=best.ev_total,
        events_ev=ev_events,
        vice_name=vice.name if vice else None,
        vice_bonus=vice.bonus_goal if vice else None,
        top_players=top_players,
    )


def analyze_match(
    home: str,
    away: str,
    roster_path: str,
    *,
    sport: str = "soccer_fifa_world_cup",
    region: str = "eu",
    refresh: bool = False,
    use_oddspapi: bool = True,
    use_scrape: bool = True,
    top_n: int = 5,
) -> MatchAnalysis:
    roster = load_roster(roster_path)
    return _analyze_with_roster(
        roster,
        sport=sport,
        region=region,
        refresh=refresh,
        use_oddspapi=use_oddspapi,
        use_scrape=use_scrape,
        top_n=top_n,
    )


def analyze_match_from_roster(
    roster: MatchRoster,
    *,
    sport: str = "soccer_fifa_world_cup",
    region: str = "eu",
    refresh: bool = False,
    use_oddspapi: bool = True,
    use_scrape: bool = True,
    top_n: int = 5,
) -> MatchAnalysis:
    """Analyze using roster parsed from FM screenshots."""
    return _analyze_with_roster(
        roster,
        sport=sport,
        region=region,
        refresh=refresh,
        use_oddspapi=use_oddspapi,
        use_scrape=use_scrape,
        top_n=top_n,
    )
