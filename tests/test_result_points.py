import pytest

from scoring.result_points import fm_points_if_correct, fm_sign


def test_sign():
    assert fm_sign(2, 1) == "1"
    assert fm_sign(1, 1) == "X"
    assert fm_sign(0, 1) == "2"


def test_standard_scoreline_payoffs():
    pts = fm_points_if_correct(1, 0, 2, 1)
    assert pts == {
        "h_pts": 4,
        "i_pts": 8,
        "j_pts": 2,
        "superbonus_pts": 12,
        "total_if_all_hit": 26,
        "sign": "1",
    }


def test_nil_nil_reduced_payoffs():
    pts = fm_points_if_correct(0, 0, 0, 0)
    assert pts["h_pts"] == 2
    assert pts["i_pts"] == 6
    assert pts["j_pts"] == 2
    assert pts["superbonus_pts"] == 8
    assert pts["total_if_all_hit"] == 18
    assert pts["sign"] == "X"


def test_ht_nil_ft_scored():
    pts = fm_points_if_correct(0, 0, 1, 1)
    assert pts["h_pts"] == 2
    assert pts["i_pts"] == 8
    assert pts["superbonus_pts"] == 12


def test_ft_nil_only():
    pts = fm_points_if_correct(0, 0, 0, 0)
    assert pts["i_pts"] == 6


def test_draw_ft():
    pts = fm_points_if_correct(1, 1, 2, 2)
    assert pts["sign"] == "X"
    assert pts["i_pts"] == 8


def test_invalid_ft_before_ht():
    with pytest.raises(ValueError, match="fewer goals"):
        fm_points_if_correct(2, 0, 1, 0)


def test_max_goals_allowed():
    pts = fm_points_if_correct(9, 9, 9, 9)
    assert pts["total_if_all_hit"] == 26


def test_over_max_goals_rejected():
    with pytest.raises(ValueError):
        fm_points_if_correct(10, 0, 10, 0)
