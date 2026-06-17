"""Tests for OddsPapi and SofaScore player prop parsing."""

from odds.oddspapi_player_props import (
    attach_oddspapi_player_props,
    discover_player_market_ids,
    extract_player_yes_probs,
)
from odds.scrape_sofascore_players import (
    extract_card_probs_from_sofa_markets,
    extract_goalscorer_from_sofa_markets,
)
from players.models import MatchRoster, PlayerBonus


def test_discover_player_market_ids():
    catalog = [
        {"marketId": 10730, "marketType": "players-anytimegoalscorer", "marketLength": 0},
        {"marketId": 102732, "marketType": "players-cards", "marketLength": 1},
        {"marketId": 102733, "marketType": "players-cards", "marketLength": 0},
    ]
    goal_id, card_id = discover_player_market_ids(catalog)
    assert goal_id == 10730
    assert card_id == 102732


def test_extract_oddspapi_goalscorer_probs():
    payload = {
        "bookmakerOdds": {
            "pinnacle": {
                "bookmakerIsActive": True,
                "markets": {
                    "10730": {
                        "marketActive": True,
                        "outcomes": {
                            "10730": {
                                "players": {
                                    "0": {
                                        "active": True,
                                        "playerName": "Harry Kane",
                                        "price": 2.1,
                                    },
                                    "1": {
                                        "active": True,
                                        "playerName": "Ivan Toney",
                                        "price": 4.5,
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    }
    probs = extract_player_yes_probs(payload, 10730)
    assert "Harry Kane" in probs
    assert probs["Harry Kane"] > 0


def test_attach_oddspapi_player_props_mock():
    roster = MatchRoster(
        match_id="T",
        home="England",
        away="Croatia",
        players=[
            PlayerBonus("Kane", "home", "FWD", bonus_goal=3),
            PlayerBonus("Modric", "away", "MID", bonus_goal=6),
        ],
    )
    from unittest.mock import patch

    fake_goals = {"Harry Kane": 0.42}
    fake_cards = {"Luka Modric": 0.18}
    with patch(
        "odds.oddspapi_player_props.fetch_oddspapi_player_props",
        return_value=(fake_goals, fake_cards, "test"),
    ):
        updated, note = attach_oddspapi_player_props(roster)
    kane = next(p for p in updated.players if p.name == "Kane")
    modric = next(p for p in updated.players if p.name == "Modric")
    assert float(kane.p_goal or 0) > 0.4
    assert float(modric.p_yellow or 0) > 0.15


def test_extract_sofa_goalscorer_markets():
    markets = [
        {
            "marketName": "Anytime goalscorer",
            "choices": [
                {"name": "Harry Kane", "decimalValue": 2.2},
                {"name": "Ivan Toney", "decimalValue": 5.0},
            ],
        }
    ]
    probs = extract_goalscorer_from_sofa_markets(markets)
    assert probs["Harry Kane"] > 0


def test_extract_sofa_card_markets():
    markets = [
        {
            "marketName": "Player to be carded",
            "choices": [
                {"name": "Luka Modric", "decimalValue": 3.1},
            ],
        }
    ]
    probs = extract_card_probs_from_sofa_markets(markets)
    assert probs["Luka Modric"] > 0
