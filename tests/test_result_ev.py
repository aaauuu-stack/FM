import pytest

from odds.distribution import build_distribution
from odds.match_loader import MatchData, MatchOdds
from predict.result_ev import compute_ev, rank_predictions
from scoring.result_points import fm_points_if_correct


def _sample_match(**overrides) -> MatchData:
    odds = MatchOdds(
        h2h={"home": 1.65, "draw": 3.80, "away": 5.00},
        totals={"line": 2.5, "over": 1.90, "under": 1.95},
    )
    base = dict(
        match_id="TEST",
        home="Home",
        away="Away",
        kickoff="2026-06-15T21:00:00",
        odds=odds,
    )
    base.update(overrides)
    return MatchData(**base)


def test_poisson_distribution_sums_to_one():
    dist = build_distribution(_sample_match())
    assert abs(sum(dist.ft_marginal.values()) - 1.0) < 0.01
    assert abs(sum(dist.sign_probs.values()) - 1.0) < 0.01


def test_ev_non_negative_for_reasonable_pick():
    dist = build_distribution(_sample_match())
    rec = compute_ev(1, 0, 2, 1, dist)
    assert rec.ev_total >= 0
    assert rec.sign == "1"


def test_rank_predictions_returns_sorted():
    _, ranked = rank_predictions(_sample_match(), top_n=3)
    assert len(ranked) == 3
    assert ranked[0].ev_total >= ranked[1].ev_total >= ranked[2].ev_total


def test_correct_score_path():
    match = _sample_match(
        odds=MatchOdds(
            correct_score={
                "1-0": 7.50,
                "2-1": 9.00,
                "0-0": 11.00,
                "1-1": 6.50,
            }
        )
    )
    dist = build_distribution(match)
    assert dist.source == "correct_score_market"
    assert dist.confidence in ("medium", "high")


def test_ht_ft_path():
    match = _sample_match(
        odds=MatchOdds(
            ht_ft={
                "1-0/2-1": 12.0,
                "0-0/0-0": 15.0,
                "1-1/1-1": 10.0,
            }
        )
    )
    dist = build_distribution(match)
    assert dist.source == "ht_ft_market"
    assert dist.joint[(1, 0, 2, 1)] > 0


def test_superbonus_payoff_total():
    pts = fm_points_if_correct(1, 0, 2, 1)
    assert pts["total_if_all_hit"] == 26
