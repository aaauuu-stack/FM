import pytest

from odds.devig import devig_two_way, proportional_devig


def test_proportional_devig_sums_to_one():
    probs = proportional_devig({"home": 2.0, "draw": 3.5, "away": 4.0})
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert set(probs) == {"home", "draw", "away"}


def test_proportional_devig_ordering():
    probs = proportional_devig({"home": 1.5, "draw": 4.0, "away": 6.0})
    assert probs["home"] > probs["draw"] > probs["away"]


def test_invalid_odds_rejected():
    with pytest.raises(ValueError):
        proportional_devig({"home": 0.9})


def test_devig_two_way():
    over, under = devig_two_way(1.90, 1.95)
    assert abs(over + under - 1.0) < 1e-9
