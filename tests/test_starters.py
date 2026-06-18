"""Tests for starter GK resolution."""

from players.models import MatchRoster, PlayerBonus
from players.starters import apply_starter_probabilities, resolve_starters
from predict.lineup_ev import optimize_lineup
from scoring.lineup_points import compute_player_ev


def _swiss_bosnia_roster() -> MatchRoster:
    players = [
        PlayerBonus(name="Keller", side="home", role="GK", bonus_goal=5, bonus_clean_sheet=6),
        PlayerBonus(name="Kobel", side="home", role="GK", bonus_goal=5, bonus_clean_sheet=5),
        PlayerBonus(name="Mvogo", side="home", role="GK", bonus_goal=6, bonus_clean_sheet=6),
        PlayerBonus(name="Hadzikic", side="away", role="GK", bonus_goal=7, bonus_clean_sheet=7),
        PlayerBonus(name="Vasilj", side="away", role="GK", bonus_goal=6, bonus_clean_sheet=6),
        PlayerBonus(name="Akanji", side="home", role="DEF", bonus_goal=8),
        PlayerBonus(name="Tabakovic", side="away", role="FWD", bonus_goal=12),
        PlayerBonus(name="Ndoye", side="home", role="MID", bonus_goal=6, vice_allenatore=True),
        PlayerBonus(name="Xhaka", side="home", role="MID", bonus_goal=8),
        PlayerBonus(name="Dedic", side="away", role="DEF", bonus_goal=8),
    ]
    return MatchRoster(match_id="SUI-BIH", home="Svizzera", away="Bosnia", players=players)


def test_resolve_starters_one_gk_per_team_with_sofa():
    from unittest.mock import patch

    from players.starters import infer_starters

    sofa_home = {"Kobel", "G. Kobel", "Embolo", "Akanji", "Xhaka"}
    sofa_away = {"Vasilj", "N. Vasilj", "Dzeko", "Dedic", "Katic"}
    with patch(
        "players.starters.fetch_event_starter_names",
        return_value=(sofa_home, sofa_away, "lineups SofaScore"),
    ):
        roster, _ = infer_starters(_swiss_bosnia_roster(), sofascore_event_id=1)
    home_gks = [p for p in roster.home_players() if p.is_goalkeeper]
    assert sum(1 for p in home_gks if p.starter) == 1
    assert next(p for p in home_gks if p.starter).name == "Kobel"
    away_gks = [p for p in roster.away_players() if p.is_goalkeeper]
    assert sum(1 for p in away_gks if p.starter) == 1
    assert next(p for p in away_gks if p.starter).name == "Vasilj"


def test_gk_fallback_picks_kobel_without_sofa():
    """Senza lineups SofaScore: portiere = bonus FM più basso (Kobel, non Keller)."""
    roster = resolve_starters(_swiss_bosnia_roster())
    home_gks = [p for p in roster.home_players() if p.is_goalkeeper]
    assert sum(1 for p in home_gks if p.starter) == 1
    assert next(p for p in home_gks if p.starter).name == "Kobel"
    away_gks = [p for p in roster.away_players() if p.is_goalkeeper]
    assert sum(1 for p in away_gks if p.starter) == 1
    assert next(p for p in away_gks if p.starter).name == "Vasilj"


def test_lineup_never_picks_three_gks():
    roster = resolve_starters(_swiss_bosnia_roster())
    for player in roster.players:
        if player.starter and player.is_goalkeeper:
            player.p_clean_sheet = 0.47
        elif player.starter:
            player.p_goal = 0.05
    roster = apply_starter_probabilities(roster)
    best, _ = optimize_lineup(roster)
    gks = [p for p in best.players if p.player.is_goalkeeper]
    assert len(gks) <= 2
    home_gks = [p for p in best.players if p.player.is_goalkeeper and p.player.side == "home"]
    assert len(home_gks) <= 1


def test_bench_gk_zero_ev():
    roster = resolve_starters(_swiss_bosnia_roster())
    for player in roster.players:
        if player.starter:
            player.p_clean_sheet = 0.5
    roster = apply_starter_probabilities(roster)
    bench = [p for p in roster.players if p.is_goalkeeper and not p.starter][0]
    assert compute_player_ev(bench).ev_total == 0.0


def test_gk_fallback_skips_quoted_backup():
    from players.starters import infer_starters

    roster = _swiss_bosnia_roster()
    for player in roster.players:
        if player.name == "Keller":
            player.book_goal_matched = True
    roster, note = infer_starters(roster)
    kobel = next(p for p in roster.players if p.name == "Kobel")
    keller = next(p for p in roster.players if p.name == "Keller")
    assert kobel.starter
    assert not keller.starter
    assert "portiere home: Kobel" in note


def test_mark_gk_goalscorer_quotes_before_infer():
    from players.starters import infer_starters, mark_gk_goalscorer_quotes

    roster = _swiss_bosnia_roster()
    roster = mark_gk_goalscorer_quotes(roster, {"Y. Keller": 0.02, "Embolo": 0.48})
    roster, _ = infer_starters(roster)
    kobel = next(p for p in roster.players if p.name == "Kobel")
    keller = next(p for p in roster.players if p.name == "Keller")
    assert kobel.starter
    assert not keller.starter
    assert keller.book_goal_matched


def test_web_search_never_marks_backup_gk():
    """Ricerca web che cita solo Keller → titolare resta Kobel."""
    from unittest.mock import patch

    from players.starters import infer_starters

    roster = _swiss_bosnia_roster()
    corpus = (
        "Svizzera convocati: Keller in porta, Akanji, Xhaka, Embolo, Widmer, "
        "Freuler, Vargas, Aebischer, Rodriguez, Elvedi. "
        "Bosnia: Hadzikic, Dedic, Kolasinac, Demirovic, Lukic, Katic."
    )
    with patch("players.lineup_web_search.web_search_enabled", return_value=True):
        with patch("players.lineup_web_search._collect_corpus", return_value=corpus):
            updated, note = infer_starters(roster)

    keller = next(p for p in updated.players if p.name == "Keller")
    kobel = next(p for p in updated.players if p.name == "Kobel")
    hadzikic = next(p for p in updated.players if p.name == "Hadzikic")
    vasilj = next(p for p in updated.players if p.name == "Vasilj")
    assert kobel.starter
    assert not keller.starter
    assert vasilj.starter
    assert not hadzikic.starter


def test_sofa_complete_lineup_excludes_backup_gk():
    """Con XI SofaScore completo, portiere backup (Keller) non è titolare."""
    from unittest.mock import patch

    from players.starters import infer_starters

    sofa_home = {
        "G. Kobel",
        "Kobel",
        "R. Rodríguez",
        "Rodriguez",
        "M. Akanji",
        "Akanji",
        "N. Elvedi",
        "Elvedi",
        "R. Freuler",
        "Freuler",
        "G. Xhaka",
        "Xhaka",
        "R. Vargas",
        "Vargas",
        "B. Embolo",
        "Embolo",
        "D. Ndoye",
        "Ndoye",
        "M. Aebischer",
        "Aebischer",
        "D. Zakaria",
        "Zakaria",
    }
    sofa_away = {
        "N. Vasilj",
        "Vasilj",
        "A. Dedić",
        "Dedic",
        "S. Kolašinac",
        "Kolasinac",
        "E. Demirović",
        "Demirovic",
        "J. Lukić",
        "Lukic",
        "N. Katić",
        "Katic",
        "T. Muharemović",
        "Muharemovic",
        "E. Bajraktarević",
        "Bajraktarevic",
        "I. Bašić",
        "Basic",
        "B. Tahirović",
        "Tahirovic",
        "A. Memić",
        "Memic",
    }
    players = [
        PlayerBonus("Keller", "home", "GK", bonus_goal=5, bonus_clean_sheet=6),
        PlayerBonus("Kobel", "home", "GK", bonus_goal=5, bonus_clean_sheet=5),
        PlayerBonus("Embolo", "home", "FWD", bonus_goal=5),
        PlayerBonus("Amdouni", "home", "FWD", bonus_goal=7),
        PlayerBonus("Vargas R.", "home", "MID", bonus_goal=7),
        PlayerBonus("Rodriguez R.", "home", "DEF", bonus_goal=9),
        PlayerBonus("Ndoye", "home", "MID", bonus_goal=6, vice_allenatore=True),
        PlayerBonus("Hadzikic", "away", "GK", bonus_goal=6, bonus_clean_sheet=6),
        PlayerBonus("Vasilj", "away", "GK", bonus_goal=6, bonus_clean_sheet=6),
        PlayerBonus("Dedic", "away", "DEF", bonus_goal=8),
        PlayerBonus("Tabakovic", "away", "FWD", bonus_goal=12),
    ]
    roster = MatchRoster("T", "Svizzera", "Bosnia", players=players)
    with patch(
        "players.starters.fetch_event_starter_names",
        return_value=(sofa_home, sofa_away, "lineups SofaScore (11+11 titolari)"),
    ):
        updated, note = infer_starters(roster, sofascore_event_id=12345)

    keller = next(p for p in updated.players if p.name == "Keller")
    kobel = next(p for p in updated.players if p.name == "Kobel")
    amdouni = next(p for p in updated.players if p.name == "Amdouni")
    hadzikic = next(p for p in updated.players if p.name == "Hadzikic")
    vasilj = next(p for p in updated.players if p.name == "Vasilj")

    assert not keller.starter
    assert kobel.starter
    assert not amdouni.starter
    assert not hadzikic.starter
    assert vasilj.starter
    assert "SofaScore formazioni" in note


def test_bench_sub_with_book_goal_zeroed_if_not_starter():
    """Panchina con quota book: P(gol) azzerata — FM non premia chi non scende."""
    from players.starters import apply_starter_probabilities

    players = [
        PlayerBonus("Kobel", "home", "GK", bonus_goal=5, bonus_clean_sheet=5, starter=True),
        PlayerBonus("Embolo", "home", "FWD", bonus_goal=5, starter=True, p_goal=0.48, book_goal_matched=True),
        PlayerBonus(
            "Amdouni",
            "home",
            "FWD",
            bonus_goal=7,
            starter=False,
            p_goal=0.37,
            book_goal_matched=True,
        ),
        PlayerBonus("Ndoye", "home", "MID", bonus_goal=6, vice_allenatore=True),
        PlayerBonus("Vasilj", "away", "GK", bonus_goal=6, bonus_clean_sheet=6, starter=True),
        PlayerBonus("Dzeko", "away", "FWD", bonus_goal=6, starter=True, p_goal=0.22, book_goal_matched=True),
        PlayerBonus("Xhaka", "home", "MID", bonus_goal=8, starter=True, p_goal=0.05),
        PlayerBonus("Dedic", "away", "DEF", bonus_goal=8, starter=True),
    ]
    roster = MatchRoster("T", "Svizzera", "Bosnia", players=players)
    roster = apply_starter_probabilities(roster)

    amdouni = next(p for p in roster.players if p.name == "Amdouni")
    assert float(amdouni.p_goal or 0) == 0.0
    assert amdouni.book_goal_matched
    assert "Amdouni" not in {p.name for p in roster.lineup_pool()}
    assert "Embolo" in {p.name for p in roster.lineup_pool()}


def test_bench_without_book_zeroed():
    roster = resolve_starters(_swiss_bosnia_roster())
    bench_fwd = PlayerBonus("BenchFwd", "home", "FWD", bonus_goal=12, p_goal=0.08)
    roster.players.append(bench_fwd)
    roster = apply_starter_probabilities(roster)
    bench = next(p for p in roster.players if p.name == "BenchFwd")
    assert float(bench.p_goal or 0) == 0.0
    assert "BenchFwd" not in {p.name for p in roster.lineup_pool()}


def test_card_quote_does_not_mark_starter():
    players = [
        PlayerBonus(name="Keller", side="home", role="GK", bonus_goal=5, bonus_clean_sheet=5),
        PlayerBonus(name="Kobel", side="home", role="GK", bonus_goal=5, bonus_clean_sheet=5),
        PlayerBonus(name="Akanji", side="home", role="DEF", bonus_goal=8),
        PlayerBonus(name="Schar", side="home", role="DEF", bonus_goal=9),
        PlayerBonus(name="Rodriguez", side="home", role="DEF", bonus_goal=10),
        PlayerBonus(name="Widmer", side="home", role="DEF", bonus_goal=11),
        PlayerBonus(name="Embolo", side="home", role="FWD", bonus_goal=5),
        PlayerBonus(name="Vargas", side="home", role="FWD", bonus_goal=7),
        PlayerBonus(name="Xhaka", side="home", role="MID", bonus_goal=8),
        PlayerBonus(name="Freuler", side="home", role="MID", bonus_goal=9),
        PlayerBonus(name="Hadzikic", side="away", role="GK", bonus_goal=6, bonus_clean_sheet=6),
        PlayerBonus(name="Dedic", side="away", role="DEF", bonus_goal=8),
        PlayerBonus(
            name="BackupDef",
            side="home",
            role="DEF",
            bonus_goal=14,
            book_card_matched=True,
            p_yellow=0.30,
        ),
    ]
    roster = resolve_starters(MatchRoster("T", "Svizzera", "Bosnia", players=players))
    backup = next(p for p in roster.players if p.name == "BackupDef")
    assert not backup.starter
    assert backup.book_card_matched
