"""Tests for unified EV reporting."""

from predict.ev_report import EvComponent, EvReport, print_ev_report, result_recommendation_to_report
from predict.result_ev import compute_ev
from odds.distribution import ScorelineDistribution


def _sample_dist() -> ScorelineDistribution:
    joint = {
        (1, 0, 2, 0): 0.12,
        (0, 0, 1, 0): 0.10,
        (1, 1, 1, 1): 0.08,
    }
    ht: dict[tuple[int, int], float] = {}
    ft: dict[tuple[int, int], float] = {}
    for (ht_h, ht_a, ft_h, ft_a), prob in joint.items():
        ht[(ht_h, ht_a)] = ht.get((ht_h, ht_a), 0.0) + prob
        ft[(ft_h, ft_a)] = ft.get((ft_h, ft_a), 0.0) + prob
    sign = {"1": 0.55, "X": 0.25, "2": 0.20}
    return ScorelineDistribution(
        joint=joint,
        ht_marginal=ht,
        ft_marginal=ft,
        sign_probs=sign,
        source="test",
        confidence="high",
    )


def test_result_recommendation_to_report_includes_ev():
    dist = _sample_dist()
    best = compute_ev(1, 0, 2, 0, dist)
    report = result_recommendation_to_report(
        "England",
        "Croatia",
        match_id="test",
        kickoff="2026-06-17",
        source_note="test",
        dist=dist,
        best=best,
        ranked=[best],
    )
    assert report.ev_total == best.ev_total
    assert len(report.components) == 4
    assert all(c.ev_pts >= 0 for c in report.components)


def test_print_ev_report_smoke(capsys):
    report = EvReport(
        title="Test",
        pick_summary="Pick A",
        ev_total=1.25,
        components=[EvComponent("Gol", 0.2, 5, 1.0)],
    )
    print_ev_report(report)
    out = capsys.readouterr().out
    assert "EV totale: 1.250 pt" in out
    assert "Giocata consigliata" in out
