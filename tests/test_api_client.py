import json
from pathlib import Path
from unittest.mock import patch

import pytest

from odds.api_client import FetchResult, _read_cache, _write_cache, fetch_odds
from odds.api_normalize import (
    event_to_match_data,
    find_event,
    normalize_team,
    team_match_score,
    teams_match,
)


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def eng_cro_events():
    return json.loads((FIXTURES / "api_eng_cro.json").read_text(encoding="utf-8"))


def test_teams_match_italian_aliases():
    assert teams_match("Inghilterra", "England")
    assert teams_match("Croazia", "Croatia")
    assert teams_match("Svizzera", "Switzerland")
    assert teams_match("Bosnia-Erzegovina", "Bosnia & Herzegovina")
    assert teams_match("Bosnia Erzegovina", "Bosnia & Herzegovina")
    assert normalize_team("Inghilterra") == "england"
    assert normalize_team("Bosnia-Erzegovina") == "bosnia herzegovina"


def test_find_event_swiss_bosnia():
    events = [
        {
            "id": "x1",
            "home_team": "Switzerland",
            "away_team": "Bosnia & Herzegovina",
            "commence_time": "2026-06-20T18:00:00Z",
            "bookmakers": [],
        }
    ]
    event = find_event(events, "Svizzera", "Bosnia-Erzegovina")
    assert event["home_team"] == "Switzerland"


def test_team_match_rejects_usa_in_australia():
    assert not teams_match("USA", "Australia")
    assert team_match_score("USA", "Australia") < 0.72


def test_find_event_swapped_roster_order():
    events = [
        {
            "id": "x1",
            "home_team": "Switzerland",
            "away_team": "Bosnia & Herzegovina",
            "commence_time": "2026-06-20T18:00:00Z",
            "bookmakers": [],
        }
    ]
    event = find_event(events, "Bosnia-Erzegovina", "Svizzera")
    assert event["home_team"] == "Switzerland"


def test_find_event_picks_best_from_list():
    events = [
        {"id": "a", "home_team": "Czech Republic", "away_team": "South Africa", "bookmakers": []},
        {"id": "b", "home_team": "Switzerland", "away_team": "Bosnia & Herzegovina", "bookmakers": []},
        {"id": "c", "home_team": "England", "away_team": "Croatia", "bookmakers": []},
    ]
    event = find_event(events, "Svizzera", "Bosnia Erzegovina")
    assert event["id"] == "b"


def test_event_to_match_data(eng_cro_events):
    match = event_to_match_data(eng_cro_events[0])
    assert match.home == "England"
    assert match.away == "Croatia"
    assert match.odds.h2h["home"] == pytest.approx(1.675, abs=0.01)
    assert match.odds.totals["line"] == 2.5
    assert "over" in match.odds.totals
    assert match.odds.ht_result["draw"] == pytest.approx(2.2, abs=0.01)


def test_find_event_italian_names(eng_cro_events):
    event = find_event(eng_cro_events, "Inghilterra", "Croazia")
    assert event["home_team"] == "England"


def test_fetch_odds_uses_cache(tmp_path, eng_cro_events):
    cache_file = tmp_path / "cache.json"
    _write_cache(cache_file, eng_cro_events, {"x-requests-remaining": "499"})

    cached = _read_cache(cache_file, ttl_seconds=3600)
    assert cached is not None
    assert len(cached) == 1

    with patch("odds.api_client._cache_path", return_value=cache_file):
        with patch("odds.api_client.get_api_key", return_value="test-key"):
            result = fetch_odds(force_refresh=False)
    assert result.from_cache is True
    assert len(result.events) == 1


def test_fetch_odds_live_mock(eng_cro_events):
    class FakeResponse:
        headers = {"x-requests-remaining": "498"}

        def read(self):
            return json.dumps(eng_cro_events).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("odds.api_client.get_api_key", return_value="test-key"):
        with patch("odds.api_client._read_cache", return_value=None):
            with patch("urllib.request.urlopen", return_value=FakeResponse()):
                result = fetch_odds(force_refresh=True)

    assert isinstance(result, FetchResult)
    assert result.from_cache is False
    assert result.events[0]["home_team"] == "England"
