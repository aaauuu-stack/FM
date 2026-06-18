"""Merge odds from multiple providers into a single MatchData."""

from __future__ import annotations

from odds.match_loader import MatchData, MatchOdds


def merge_odds(base: MatchOdds, overlay: MatchOdds) -> MatchOdds:
    """
    Overlay specialist markets (OddsPapi correct score) onto The Odds API base.

    Priority: overlay wins for specialist markets; base keeps h2h/totals/ht_result.
    """
    merged = MatchOdds(
        h2h=dict(base.h2h),
        totals=dict(base.totals),
        correct_score=dict(base.correct_score),
        ht_ft=dict(base.ht_ft),
        ht_result=dict(base.ht_result),
        half_time_correct_score=dict(base.half_time_correct_score),
    )

    if overlay.correct_score:
        merged.correct_score = dict(overlay.correct_score)
    if overlay.half_time_correct_score:
        merged.half_time_correct_score = dict(overlay.half_time_correct_score)
    if overlay.ht_ft:
        merged.ht_ft = dict(overlay.ht_ft)
    if overlay.ht_result and not merged.ht_result:
        merged.ht_result = dict(overlay.ht_result)

    return merged


def merge_odds_fill_gaps(base: MatchOdds, supplemental: MatchOdds) -> MatchOdds:
    """Fill only empty specialist markets from supplemental overlay."""
    merged = merge_odds(base, MatchOdds())
    if supplemental.correct_score and not merged.correct_score:
        merged.correct_score = dict(supplemental.correct_score)
    if supplemental.half_time_correct_score and not merged.half_time_correct_score:
        merged.half_time_correct_score = dict(supplemental.half_time_correct_score)
    if supplemental.ht_ft and not merged.ht_ft:
        merged.ht_ft = dict(supplemental.ht_ft)
    if supplemental.ht_result and not merged.ht_result:
        merged.ht_result = dict(supplemental.ht_result)
    return merged


def merge_match_data_fill_gaps(base: MatchData, supplemental: MatchOdds) -> MatchData:
    return MatchData(
        match_id=base.match_id,
        home=base.home,
        away=base.away,
        kickoff=base.kickoff,
        odds=merge_odds_fill_gaps(base.odds, supplemental),
    )


def merge_match_data(base: MatchData, overlay: MatchOdds) -> MatchData:
    return MatchData(
        match_id=base.match_id,
        home=base.home,
        away=base.away,
        kickoff=base.kickoff,
        odds=merge_odds(base.odds, overlay),
    )


def needs_correct_score(odds: MatchOdds) -> bool:
    """True if FT or HT correct-score markets are still missing."""
    return not odds.correct_score or not odds.half_time_correct_score
