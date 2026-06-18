"""Tests for SofaScore GK web fallback."""

from odds.sofascore_gk_fallback import parse_gk_starters_from_sofa_text


def test_parse_gk_from_sofa_news_text():
    text = (
        "Switzerland line up in a 4-3-3 with Kobel in goal, a Rodriguez-Akanji base. "
        "Bosnia and Herzegovina are listed in a 4-4-2, anchored by Vasilj in goal."
    )
    home, away = parse_gk_starters_from_sofa_text(
        text,
        home_team="Switzerland",
        away_team="Bosnia & Herzegovina",
    )
    assert home == {"Kobel"}
    assert away == {"Vasilj"}


def test_parse_gk_ignores_unrelated_sentences():
    text = "Another match with Keller in goal for a club side."
    home, away = parse_gk_starters_from_sofa_text(
        text,
        home_team="Switzerland",
        away_team="Bosnia & Herzegovina",
    )
    assert home == set()
    assert away == set()


def test_fetch_event_gk_starter_names_web_fallback(monkeypatch):
    """When lineup API is empty, read GK from SofaScore news pages."""
    from odds.scrape_sofascore_subs import fetch_event_gk_starter_names

    monkeypatch.setattr(
        "odds.scrape_sofascore_subs._fetch_lineups",
        lambda _eid: None,
    )
    monkeypatch.setattr(
        "odds.sofascore_gk_fallback.fetch_gk_starters_from_sofascore_web",
        lambda _eid: ({"Kobel"}, {"Vasilj"}, "SofaScore news"),
    )
    home, away = fetch_event_gk_starter_names(15186806)
    assert home == {"Kobel"}
    assert away == {"Vasilj"}
