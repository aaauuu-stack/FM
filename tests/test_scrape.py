from unittest.mock import patch

from odds.match_loader import MatchOdds
from odds.merge_providers import merge_odds_fill_gaps
from odds.score_parsing import parse_score_outcome
from odds.scrape_normalize import fetch_scraped_match_odds
from odds.scrape_sofascore import _extract_ft_markets, _extract_ht_markets


SOFA_MARKETS = [
    {
        "marketName": "Correct score",
        "choices": [
            {"name": "1:0", "decimalValue": 7.0},
            {"name": "2:1", "decimalValue": 9.0},
        ],
    },
    {
        "marketName": "1st half - Correct score",
        "choices": [
            {"name": "1-0", "decimalValue": 5.0},
            {"name": "0-0", "decimalValue": 6.0},
        ],
    },
]


def test_parse_score_outcome():
    assert parse_score_outcome("1:0") == (1, 0)
    assert parse_score_outcome("2 - 1") == (2, 1)


def test_extract_from_sofascore_markets():
    ft = _extract_ft_markets(SOFA_MARKETS)
    ht = _extract_ht_markets(SOFA_MARKETS)
    assert ft == {"1-0": 7.0, "2-1": 9.0}
    assert ht == {"1-0": 5.0, "0-0": 6.0}


def test_merge_odds_fill_gaps():
    base = MatchOdds(h2h={"home": 1.6, "draw": 3.8, "away": 5.0})
    supplemental = MatchOdds(
        correct_score={"1-0": 7.0},
        half_time_correct_score={"0-0": 6.0},
    )
    merged = merge_odds_fill_gaps(base, supplemental)
    assert merged.h2h["home"] == 1.6
    assert merged.correct_score["1-0"] == 7.0
    assert merged.half_time_correct_score["0-0"] == 6.0


def test_fetch_scraped_match_odds_mock():
    existing = MatchOdds(h2h={"home": 1.6, "draw": 3.8, "away": 5.0})
    sofa = MatchOdds(
        correct_score={"1-0": 7.0},
        half_time_correct_score={"0-0": 6.0},
    )
    with patch("odds.scrape_normalize.fetch_sofascore_match_odds", return_value=sofa):
        overlay, sources = fetch_scraped_match_odds("England", "Croatia", existing)

    assert overlay.correct_score == {"1-0": 7.0}
    assert overlay.half_time_correct_score == {"0-0": 6.0}
    assert sources == ["SofaScore"]


def test_fetch_scraped_skips_when_complete():
    existing = MatchOdds(
        correct_score={"1-0": 7.0},
        half_time_correct_score={"0-0": 6.0},
    )
    overlay, sources = fetch_scraped_match_odds("England", "Croatia", existing)
    assert overlay.correct_score == {}
    assert sources == []
