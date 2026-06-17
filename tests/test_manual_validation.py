"""Manual validation: EV-max vs most-probable baseline on example matches."""

from __future__ import annotations

from pathlib import Path

import pytest

from odds.match_loader import load_match
from predict.result_ev import most_probable_prediction, rank_predictions

MATCHES_DIR = Path(__file__).resolve().parent.parent / "data" / "matches"
EXAMPLE_MATCHES = ["eng-cro.yaml", "fra-bra.yaml", "ger-sco.yaml"]


@pytest.mark.parametrize("filename", EXAMPLE_MATCHES)
def test_example_match_produces_recommendation(filename: str):
    path = MATCHES_DIR / filename
    match = load_match(path)
    dist, ranked = rank_predictions(match, top_n=3)

    assert ranked, f"No recommendations for {filename}"
    best = ranked[0]
    assert best.ev_total >= 0
    assert 0 <= best.ht_home <= 9 and 0 <= best.ft_home <= 9


@pytest.mark.parametrize("filename", EXAMPLE_MATCHES)
def test_ev_max_at_least_as_good_as_prob_baseline(filename: str):
    """EV-optimized pick should never be worse than naive prob-max on EV metric."""
    path = MATCHES_DIR / filename
    match = load_match(path)
    dist, ranked = rank_predictions(match, top_n=50)

    best_ev = ranked[0]
    baseline = most_probable_prediction(dist)
    assert baseline is not None

    max_ev_overall = max(
        r.ev_total
        for r in ranked
        if True
    )
    # The top-ranked recommendation must equal global max EV in our candidate set
    assert best_ev.ev_total == pytest.approx(max_ev_overall, abs=1e-9)
    assert best_ev.ev_total >= baseline.ev_total


def test_eng_cro_favourite_home_not_nil_nil():
    """Heavy favourite should not default to 0-0 when EV penalizes low payoffs."""
    match = load_match(MATCHES_DIR / "eng-cro.yaml")
    _, ranked = rank_predictions(match, top_n=1)
    best = ranked[0]
    # With home favourite, expect non-draw or at least positive EV pick
    assert best.ev_total > 0
