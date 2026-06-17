import pytest

from odds.betfair_normalize import parse_runner_score, _runners_to_score_odds
from odds.distribution import _distribution_from_dual_correct_score
from odds.merge_providers import merge_odds
from odds.match_loader import MatchOdds


def test_parse_runner_score():
    assert parse_runner_score("1 - 0") == (1, 0)
    assert parse_runner_score("2-1") == (2, 1)
    assert parse_runner_score("Any Other Home Win") is None


def test_runners_to_score_odds():
    book = {
        "runners": [
            {"runnerName": "1 - 0", "ex": {"availableToBack": [{"price": 7.0}]}},
            {"runnerName": "2 - 1", "ex": {"availableToBack": [{"price": 9.0}]}},
            {"runnerName": "Any Other Draw", "ex": {"availableToBack": [{"price": 4.0}]}},
        ]
    }
    odds = _runners_to_score_odds(book)
    assert odds == {"1-0": 7.0, "2-1": 9.0}


def test_dual_correct_score_distribution():
    dist = _distribution_from_dual_correct_score(
        {"1-0": 7.0, "2-1": 9.0},
        {"1-0": 5.0, "0-0": 6.0},
    )
    assert dist.source == "dual_correct_score"
    assert dist.confidence == "high"
    assert abs(sum(dist.joint.values()) - 1.0) < 1e-9
    assert dist.joint.get((1, 0, 1, 0), 0) > 0
    assert dist.joint.get((0, 0, 2, 1), 0) > 0


def test_merge_odds_betfair_overlay():
    base = MatchOdds(
        h2h={"home": 1.6, "draw": 3.8, "away": 5.0},
        totals={"line": 2.5, "over": 1.9, "under": 1.95},
    )
    overlay = MatchOdds(
        correct_score={"1-0": 7.0, "2-1": 9.0},
        half_time_correct_score={"1-0": 5.0, "0-0": 6.0},
    )
    merged = merge_odds(base, overlay)
    assert merged.h2h["home"] == 1.6
    assert merged.correct_score["2-1"] == 9.0
    assert merged.half_time_correct_score["0-0"] == 6.0
