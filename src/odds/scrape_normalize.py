"""Fill missing correct-score markets via web sources."""

from __future__ import annotations

from odds.match_loader import MatchOdds
from odds.scrape_sofascore import fetch_sofascore_match_odds


def _needs_scrape(existing: MatchOdds) -> bool:
    return not existing.correct_score or not existing.half_time_correct_score


def fetch_scraped_match_odds(
    home_query: str,
    away_query: str,
    existing: MatchOdds,
    *,
    kickoff_iso: str | None = None,
) -> tuple[MatchOdds, list[str]]:
    """
    Fetch only missing correct-score fields from web sources.

    Returns (overlay MatchOdds, list of source labels used).
    """
    if not _needs_scrape(existing):
        return MatchOdds(), []

    overlay = MatchOdds()
    sources: list[str] = []

    try:
        sofa = fetch_sofascore_match_odds(home_query, away_query, kickoff_iso=kickoff_iso)
        if not existing.correct_score and sofa.correct_score:
            overlay.correct_score = dict(sofa.correct_score)
        if not existing.half_time_correct_score and sofa.half_time_correct_score:
            overlay.half_time_correct_score = dict(sofa.half_time_correct_score)
        if overlay.correct_score or overlay.half_time_correct_score:
            sources.append("SofaScore")
    except (RuntimeError, ValueError):
        pass

    if not overlay.correct_score and not overlay.half_time_correct_score:
        hint = ""
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            hint = " Installa curl_cffi: pip install curl_cffi"
        raise ValueError(
            f"Scraping non ha trovato correct score per {home_query} vs {away_query}.{hint}"
        )

    return overlay, sources
