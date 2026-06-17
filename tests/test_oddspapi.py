from unittest.mock import patch

import pytest

from odds.score_parsing import parse_score_outcome
from odds.oddspapi_normalize import (
    _discover_market_ids,
    _extract_market_odds,
    fetch_oddspapi_match_odds,
)


CATALOG = [
    {
        "marketId": 10336,
        "marketName": "Correct Score Full Time",
        "marketType": "correctscore",
        "sportId": 10,
        "period": "fulltime",
        "outcomes": [
            {"outcomeId": 1, "outcomeName": "1-0"},
            {"outcomeId": 2, "outcomeName": "2-1"},
        ],
    },
    {
        "marketId": 102462,
        "marketName": "Correct Score First Half",
        "marketType": "correctscore",
        "sportId": 10,
        "period": "p1",
        "outcomes": [
            {"outcomeId": 10, "outcomeName": "1-0"},
            {"outcomeId": 11, "outcomeName": "0-0"},
        ],
    },
]

ODDS_PAYLOAD = {
    "bookmakerOdds": {
        "pinnacle": {
            "markets": {
                "10336": {
                    "outcomes": {
                        "1": {"players": {"0": {"price": 7.0, "active": True}}},
                        "2": {"players": {"0": {"price": 9.0, "active": True}}},
                    }
                },
                "102462": {
                    "outcomes": {
                        "10": {"players": {"0": {"price": 5.0, "active": True}}},
                        "11": {"players": {"0": {"price": 6.0, "active": True}}},
                    }
                },
            }
        }
    }
}

FIXTURES = [
    {
        "fixtureId": "abc123",
        "participant1Name": "England",
        "participant2Name": "Croatia",
    }
]


def test_parse_score_outcome():
    assert parse_score_outcome("1-0") == (1, 0)
    assert parse_score_outcome("2 - 1") == (2, 1)
    assert parse_score_outcome("Any Other") is None


def test_discover_market_ids():
    ft_id, ht_id = _discover_market_ids(CATALOG)
    assert ft_id == 10336
    assert ht_id == 102462


def test_extract_market_odds_uses_catalog_names():
    odds = _extract_market_odds(ODDS_PAYLOAD, 10336, CATALOG)
    assert odds == {"1-0": 7.0, "2-1": 9.0}


def test_fetch_oddspapi_match_odds_mock():
    with patch("odds.oddspapi_normalize.fetch_markets_catalog", return_value=CATALOG):
        with patch("odds.oddspapi_normalize.fetch_fixtures", return_value=FIXTURES):
            with patch("odds.oddspapi_normalize.fetch_odds", return_value=ODDS_PAYLOAD):
                result = fetch_oddspapi_match_odds("England", "Croatia")

    assert result.correct_score == {"1-0": 7.0, "2-1": 9.0}
    assert result.half_time_correct_score == {"1-0": 5.0, "0-0": 6.0}


def test_fetch_oddspapi_italian_team_names():
    with patch("odds.oddspapi_normalize.fetch_markets_catalog", return_value=CATALOG):
        with patch("odds.oddspapi_normalize.fetch_fixtures", return_value=FIXTURES):
            with patch("odds.oddspapi_normalize.fetch_odds", return_value=ODDS_PAYLOAD):
                result = fetch_oddspapi_match_odds("Inghilterra", "Croazia")

    assert result.correct_score["1-0"] == 7.0
