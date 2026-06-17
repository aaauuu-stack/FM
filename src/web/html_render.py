"""Render EvReport and MatchAnalysis as HTML."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from predict.analyze import MatchAnalysis
    from predict.ev_report import EvReport


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _esc(text: str) -> str:
    return html.escape(str(text))


def render_ev_report(report: EvReport) -> str:
    meta_html = ""
    if report.meta:
        items = " · ".join(f"<strong>{_esc(k)}:</strong> {_esc(v)}" for k, v in report.meta.items())
        meta_html = f'<p class="meta">{items}</p>'

    rows = []
    for c in report.components:
        if c.payoff_pts:
            sign = "-" if c.ev_pts < 0 else ""
            rows.append(
                f"<tr><td>{_esc(c.label)}</td>"
                f"<td>{_pct(c.probability)}</td>"
                f"<td>{c.payoff_pts:+d} pt</td>"
                f"<td>{sign}{abs(c.ev_pts):.3f} pt</td></tr>"
            )
        else:
            rows.append(
                f"<tr><td colspan='3'>{_esc(c.label)}</td>"
                f"<td>{c.ev_pts:.3f} pt</td></tr>"
            )

    table = (
        "<table><thead><tr><th>Componente</th><th>P</th><th>Payoff</th><th>EV</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )

    baseline = ""
    if report.baseline_summary is not None and report.baseline_ev is not None:
        delta = report.ev_total - report.baseline_ev
        baseline = (
            f'<p class="baseline">vs più probabile: {_esc(report.baseline_summary)} '
            f"(EV {_esc(f'{report.baseline_ev:.3f}')} pt, "
            f"vantaggio {delta:+.3f} pt)</p>"
        )

    alts = ""
    if report.alternatives:
        items = "".join(
            f"<li>{_esc(summary)} — EV {ev:.3f} pt</li>"
            for summary, ev in report.alternatives
        )
        alts = f"<ul class='alts'>{items}</ul>"

    return f"""
<section class="report">
  <h2>{_esc(report.title)}</h2>
  {meta_html}
  <p class="pick"><strong>Giocata:</strong> {_esc(report.pick_summary)}</p>
  <p class="ev-total">EV totale: <strong>{report.ev_total:.3f} pt</strong></p>
  {table}
  {baseline}
  {alts}
</section>
"""


def render_analysis(analysis: MatchAnalysis) -> str:
    parts = []
    if analysis.result:
        parts.append(render_ev_report(analysis.result))
    if analysis.first_sub:
        parts.append(render_ev_report(analysis.first_sub))
    if analysis.first_card:
        parts.append(render_ev_report(analysis.first_card))
    if analysis.lineup:
        parts.append(render_ev_report(analysis.lineup))

    summary = (
        f"<p class='summary'>EV formazione: <strong>{analysis.lineup_ev:.3f} pt</strong>"
    )
    if analysis.events_ev:
        summary += f" · EV eventi K+L: <strong>{analysis.events_ev:.3f} pt</strong>"
    summary += "</p>"

    if analysis.requests_remaining is not None:
        summary += f"<p class='meta'>Crediti Odds API rimanenti: {analysis.requests_remaining}</p>"

    if analysis.vice_name:
        summary += (
            f"<p class='meta'>Vice allenatore (fisso): {_esc(analysis.vice_name)} "
            f"(bonus +{analysis.vice_bonus})</p>"
        )

    top = ""
    if analysis.top_players:
        items = []
        for pev in analysis.top_players:
            malus = f", malus -{pev.ev_malus:.2f}" if pev.ev_malus else ""
            items.append(
                f"<li>{_esc(pev.player.name)} ({_esc(pev.player.role)}, "
                f"+{pev.player.bonus_goal}): EV {pev.ev_total:.3f} pt{malus}</li>"
            )
        top = f"<section><h3>Top giocatori (EV singolo)</h3><ul>{''.join(items)}</ul></section>"

    warnings = ""
    if analysis.warnings:
        items = "".join(f"<li>{_esc(w)}</li>" for w in analysis.warnings)
        warnings = f"<ul class='warnings'>{items}</ul>"

    return f"""
<article class="analysis">
  <h1>{_esc(analysis.home)} — {_esc(analysis.away)}</h1>
  <p class="meta">Fonte: {_esc(analysis.source_note)}</p>
  {warnings}
  {summary}
  {''.join(parts)}
  {top}
</article>
"""
