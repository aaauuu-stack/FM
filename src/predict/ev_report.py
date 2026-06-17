"""Unified EV reporting for recommendations (results, lineup, future phases)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from odds.distribution import ScorelineDistribution
from predict.lineup_ev import LineupRecommendation
from predict.event_ev import EventRecommendation
from predict.result_ev import ResultRecommendation, format_score, most_probable_prediction


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


@dataclass
class EvComponent:
    """Single scoring component with probability, payoff and expected value."""

    label: str
    probability: float
    payoff_pts: int
    ev_pts: float


@dataclass
class EvReport:
    """Any recommended pick with total EV and per-component breakdown."""

    title: str
    pick_summary: str
    ev_total: float
    components: list[EvComponent]
    meta: dict[str, str] | None = None
    alternatives: list[tuple[str, float]] | None = None
    baseline_summary: str | None = None
    baseline_ev: float | None = None


class HasEvTotal(Protocol):
    ev_total: float


def result_recommendation_to_report(
    match_home: str,
    match_away: str,
    *,
    match_id: str,
    kickoff: str,
    source_note: str,
    dist: ScorelineDistribution,
    best: ResultRecommendation,
    ranked: list[ResultRecommendation],
    top_n: int = 5,
) -> EvReport:
    baseline = most_probable_prediction(dist)
    baseline_summary: str | None = None
    baseline_ev: float | None = None
    if baseline and (
        baseline.ht_home != best.ht_home
        or baseline.ht_away != best.ht_away
        or baseline.ft_home != best.ft_home
        or baseline.ft_away != best.ft_away
    ):
        baseline_summary = (
            f"1T {format_score(baseline.ht_home, baseline.ht_away)} | "
            f"FT {format_score(baseline.ft_home, baseline.ft_away)} | Segno {baseline.sign}"
        )
        baseline_ev = baseline.ev_total

    alts: list[tuple[str, float]] = []
    for alt in ranked[1:top_n]:
        summary = (
            f"1T {format_score(alt.ht_home, alt.ht_away)} | "
            f"FT {format_score(alt.ft_home, alt.ft_away)} | Segno {alt.sign}"
        )
        alts.append((summary, alt.ev_total))

    return EvReport(
        title=f"{match_home} - {match_away}",
        pick_summary=(
            f"1T {format_score(best.ht_home, best.ht_away)} | "
            f"FT {format_score(best.ft_home, best.ft_away)} | Segno {best.sign}"
        ),
        ev_total=best.ev_total,
        components=[
            EvComponent("H (1T esatto)", best.p_ht_exact, best.h_pts, best.ev_breakdown["h"]),
            EvComponent("I (FT esatto)", best.p_ft_exact, best.i_pts, best.ev_breakdown["i"]),
            EvComponent("J (segno)", best.p_sign, best.j_pts, best.ev_breakdown["j"]),
            EvComponent(
                "Superbonus H+I+J",
                best.p_superbonus,
                best.superbonus_pts,
                best.ev_breakdown["superbonus"],
            ),
        ],
        meta={
            "ID": match_id,
            "Kickoff": kickoff,
            "Fonte": source_note,
            "Modello": dist.source,
            "Confidenza": dist.confidence,
        },
        alternatives=alts or None,
        baseline_summary=baseline_summary,
        baseline_ev=baseline_ev,
    )


def lineup_recommendation_to_report(
    match_home: str,
    match_away: str,
    best: LineupRecommendation,
    *,
    source_note: str,
    alternatives: list[LineupRecommendation] | None = None,
    baseline: LineupRecommendation | None = None,
) -> EvReport:
    components: list[EvComponent] = []
    for pev in best.all_players:
        prefix = pev.player.name
        if pev.player.vice_allenatore:
            prefix = f"{prefix} (VA)"
        label_base = f"{prefix} ({pev.player.role})"

        for key, ev_pts in pev.breakdown.items():
            if key == "malus":
                components.append(
                    EvComponent(
                        f"{label_base} malus",
                        pev.player.p_yellow or 0.0,
                        -1,
                        ev_pts,
                    )
                )
                continue
            payoff_map = {
                "gol_azione": pev.player.bonus_goal,
                "gol_rigore": 3,
                "gol_portiere": 10,
                "clean_sheet": pev.player.bonus_clean_sheet or 1,
                "rigore_parato": 4,
            }
            prob_map = {
                "gol_azione": pev.p_goal_action,
                "gol_rigore": pev.player.p_penalty_scored or 0.0,
                "gol_portiere": pev.player.p_gk_goal or 0.0,
                "clean_sheet": pev.p_clean_sheet,
                "rigore_parato": pev.player.p_penalty_saved or 0.0,
            }
            label_suffix = key.replace("_", " ")
            components.append(
                EvComponent(
                    f"{label_base} {label_suffix}",
                    prob_map.get(key, 0.0),
                    payoff_map.get(key, 0),
                    ev_pts,
                )
            )

        if not pev.breakdown:
            components.append(
                EvComponent(label_base, pev.p_goal_action, pev.player.bonus_goal, pev.ev_total)
            )

    pick = " | ".join(best.names)
    alts: list[tuple[str, float]] = []
    if alternatives:
        for alt in alternatives:
            alts.append((" | ".join(alt.names), alt.ev_total))

    baseline_summary = None
    baseline_ev = None
    if baseline and baseline.names != best.names:
        baseline_summary = " | ".join(baseline.names)
        baseline_ev = baseline.ev_total

    return EvReport(
        title=f"{match_home} - {match_away} — Formazione",
        pick_summary=pick,
        ev_total=best.ev_total,
        components=components,
        meta={"Fonte probabilita": source_note},
        alternatives=alts or None,
        baseline_summary=baseline_summary,
        baseline_ev=baseline_ev,
    )


def event_recommendation_to_report(rec: EventRecommendation) -> EvReport:
    meta = {"Fonte": rec.source_note} if rec.source_note else None
    return EvReport(
        title=f"Pronostico {rec.event_code} — {rec.event_label}",
        pick_summary=rec.player_name,
        ev_total=rec.ev,
        components=[
            EvComponent(
                rec.event_label,
                rec.probability,
                rec.payoff_pts,
                rec.ev,
            )
        ],
        meta=meta,
    )


def print_ev_report(report: EvReport) -> None:
    """Print recommendation + EV breakdown (all phases)."""
    print(f"\n{'=' * 60}")
    print(f"{report.title}")
    if report.meta:
        meta_line = " | ".join(f"{key}: {value}" for key, value in report.meta.items())
        print(meta_line)
    print()
    print(f"Giocata consigliata: {report.pick_summary}")
    print(f"EV totale: {report.ev_total:.3f} pt")
    print()
    print("Breakdown EV:")
    for component in report.components:
        if component.payoff_pts:
            sign = "-" if component.ev_pts < 0 else ""
            print(
                f"  {component.label:<28} "
                f"P={_pct(component.probability)} x {component.payoff_pts:+d} pt "
                f"-> {sign}{abs(component.ev_pts):.3f} pt"
            )
        else:
            print(f"  {component.label:<18} -> {component.ev_pts:.3f} pt")

    if report.baseline_summary is not None and report.baseline_ev is not None:
        delta = report.ev_total - report.baseline_ev
        print()
        print(f"  vs piu probabile: {report.baseline_summary}")
        print(f"  EV probabile: {report.baseline_ev:.3f} pt | Vantaggio EV: {delta:+.3f} pt")

    if report.alternatives:
        print()
        print("Alternative:")
        for idx, (summary, ev) in enumerate(report.alternatives, start=2):
            print(f"  {idx}. {summary} | EV={ev:.3f} pt")
