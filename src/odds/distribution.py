"""Scoreline probability distributions from bookmaker odds."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from odds.devig import devig_two_way, proportional_devig
from odds.match_loader import MatchData
from scoring.result_points import fm_sign

MAX_GOALS = 9
DEFAULT_HT_GOAL_SHARE = 0.45


@dataclass
class ScorelineDistribution:
    """Joint and marginal probabilities for HT/FT scorelines."""

    # P(HT home, HT away, FT home, FT away) — sparse dict
    joint: dict[tuple[int, int, int, int], float]
    ht_marginal: dict[tuple[int, int], float]
    ft_marginal: dict[tuple[int, int], float]
    sign_probs: dict[str, float]
    source: str
    confidence: str


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return float(np.exp(-lam) * (lam**k) / math.factorial(k))


def _build_poisson_matrix(lambda_home: float, lambda_away: float) -> np.ndarray:
    matrix = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            matrix[h, a] = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
    total = matrix.sum()
    if total > 0:
        matrix /= total
    return matrix


def _score_matrix_probs(matrix: np.ndarray) -> dict[str, float]:
    home = float(np.tril(matrix, k=-1).sum())
    draw = float(np.trace(matrix))
    away = float(np.triu(matrix, k=1).sum())
    return {"1": home, "X": draw, "2": away}


def _expected_total_goals(matrix: np.ndarray) -> float:
    total = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            total += (h + a) * matrix[h, a]
    return total


def _calibrate_lambdas(
    p_home: float,
    p_draw: float,
    p_away: float,
    expected_total: float | None = None,
) -> tuple[float, float]:
    """Find Poisson rates matching 1X2 and optionally total goals."""

    def score_matrix(lh: float, la: float) -> np.ndarray:
        return _build_poisson_matrix(lh, la)

    def error(lh: float, la: float) -> float:
        if lh <= 0 or la <= 0:
            return 1e9
        matrix = score_matrix(lh, la)
        probs = _score_matrix_probs(matrix)
        err = (probs["1"] - p_home) ** 2 + (probs["X"] - p_draw) ** 2 + (probs["2"] - p_away) ** 2
        if expected_total is not None:
            err += 0.5 * (_expected_total_goals(matrix) - expected_total) ** 2
        return err

    best_lh, best_la, best_err = 0.5, 0.5, error(0.5, 0.5)
    for lh in np.linspace(0.2, 3.5, 40):
        for la in np.linspace(0.2, 3.5, 40):
            err = error(lh, la)
            if err < best_err:
                best_lh, best_la, best_err = lh, la, err

    # Local refinement
    for lh in np.linspace(max(0.1, best_lh - 0.3), best_lh + 0.3, 15):
        for la in np.linspace(max(0.1, best_la - 0.3), best_la + 0.3, 15):
            err = error(lh, la)
            if err < best_err:
                best_lh, best_la, best_err = lh, la, err

    return best_lh, best_la


def _parse_ht_ft_key(key: str) -> tuple[int, int, int, int]:
    """Parse '1-0/2-1' into (ht_h, ht_a, ft_h, ft_a)."""
    ht_part, ft_part = key.split("/")
    ht_h, ht_a = (int(x) for x in ht_part.split("-"))
    ft_h, ft_a = (int(x) for x in ft_part.split("-"))
    if ft_h < ht_h or ft_a < ht_a:
        raise ValueError(f"Invalid HT/FT key '{key}': FT cannot trail HT")
    return ht_h, ht_a, ft_h, ft_a


def _distribution_from_ht_ft(odds: dict[str, float]) -> ScorelineDistribution:
    probs = proportional_devig(odds)
    joint: dict[tuple[int, int, int, int], float] = {}
    ht_marginal: dict[tuple[int, int], float] = {}
    ft_marginal: dict[tuple[int, int], float] = {}

    for key, prob in probs.items():
        ht_h, ht_a, ft_h, ft_a = _parse_ht_ft_key(key)
        joint[(ht_h, ht_a, ft_h, ft_a)] = prob
        ht_marginal[(ht_h, ht_a)] = ht_marginal.get((ht_h, ht_a), 0.0) + prob
        ft_marginal[(ft_h, ft_a)] = ft_marginal.get((ft_h, ft_a), 0.0) + prob

    sign_probs = {"1": 0.0, "X": 0.0, "2": 0.0}
    for (ft_h, ft_a), prob in ft_marginal.items():
        sign_probs[fm_sign(ft_h, ft_a)] += prob

    return ScorelineDistribution(
        joint=joint,
        ht_marginal=ht_marginal,
        ft_marginal=ft_marginal,
        sign_probs=sign_probs,
        source="ht_ft_market",
        confidence="high",
    )


def _distribution_from_correct_score(
    cs_odds: dict[str, float],
    ht_result_odds: dict[str, float] | None = None,
    ht_goal_share: float = DEFAULT_HT_GOAL_SHARE,
) -> ScorelineDistribution:
    ft_marginal_raw = proportional_devig(cs_odds)

    if ht_result_odds:
        ht_sign_probs = proportional_devig(ht_result_odds)
    else:
        ht_sign_probs = None

    # Build FT matrix from correct score
    ft_matrix = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
    for key, prob in ft_marginal_raw.items():
        h, a = (int(x) for x in key.split("-"))
        ft_matrix[h, a] = prob

    # Estimate HT marginal by splitting each FT scoreline
    joint: dict[tuple[int, int, int, int], float] = {}
    ht_marginal: dict[tuple[int, int], float] = {}
    ft_marginal: dict[tuple[int, int], float] = {
        tuple(int(x) for x in key.split("-")): prob for key, prob in ft_marginal_raw.items()
    }

    for (ft_h, ft_a), ft_prob in ft_marginal.items():
        if ft_prob <= 0:
            continue
        ht_candidates: list[tuple[int, int, float]] = []
        for ht_h in range(ft_h + 1):
            for ht_a in range(ft_a + 1):
                # Weight by binomial-like split of goals between halves
                weight = 1.0
                if ht_sign_probs is not None:
                    sign = fm_sign(ht_h, ht_a)
                    weight *= ht_sign_probs.get(sign, 0.01)
                # Prefer plausible HT shares
                if ft_h + ft_a > 0:
                    ht_share = (ht_h + ht_a) / (ft_h + ft_a)
                    weight *= np.exp(-((ht_share - ht_goal_share) ** 2) / 0.05)
                ht_candidates.append((ht_h, ht_a, weight))

        total_w = sum(w for _, _, w in ht_candidates)
        if total_w <= 0:
            continue

        for ht_h, ht_a, weight in ht_candidates:
            p = ft_prob * weight / total_w
            key = (ht_h, ht_a, ft_h, ft_a)
            joint[key] = joint.get(key, 0.0) + p
            ht_marginal[(ht_h, ht_a)] = ht_marginal.get((ht_h, ht_a), 0.0) + p

    # Normalize joint and rebuild marginals
    total = sum(joint.values())
    if total > 0:
        joint = {k: v / total for k, v in joint.items()}
        ht_marginal = {}
        ft_marginal = {}
        for (ht_h, ht_a, ft_h, ft_a), prob in joint.items():
            ht_marginal[(ht_h, ht_a)] = ht_marginal.get((ht_h, ht_a), 0.0) + prob
            ft_marginal[(ft_h, ft_a)] = ft_marginal.get((ft_h, ft_a), 0.0) + prob

    sign_probs = {"1": 0.0, "X": 0.0, "2": 0.0}
    for (ft_h, ft_a), prob in ft_marginal.items():
        sign_probs[fm_sign(ft_h, ft_a)] += prob

    return ScorelineDistribution(
        joint=joint,
        ht_marginal=ht_marginal,
        ft_marginal=ft_marginal,
        sign_probs=sign_probs,
        source="correct_score_market",
        confidence="high" if ht_result_odds else "medium",
    )


def _distribution_from_poisson(
    match: MatchData,
    ht_goal_share: float = DEFAULT_HT_GOAL_SHARE,
) -> ScorelineDistribution:
    h2h_probs = proportional_devig(match.odds.h2h)

    expected_total: float | None = None
    if match.odds.totals:
        line = match.odds.totals["line"]
        over_price = match.odds.totals.get("over")
        under_price = match.odds.totals.get("under")
        if over_price and under_price:
            p_over, _ = devig_two_way(over_price, under_price)
            # Rough mapping: solve for E[total] such that P(total > line) ≈ p_over
            # Use grid search on lambda sum
            best_etg, best_err = line + 0.5, 1.0
            for etg in np.linspace(0.5, 5.5, 100):
                # Approximate with Poisson total
                p_over_est = 1.0 - sum(
                    _poisson_pmf(k, etg) for k in range(int(line) + 1)
                )
                err = abs(p_over_est - p_over)
                if err < best_err:
                    best_etg, best_err = etg, err
            expected_total = best_etg

    lambda_home, lambda_away = _calibrate_lambdas(
        h2h_probs["home"],
        h2h_probs["draw"],
        h2h_probs["away"],
        expected_total,
    )

    ft_matrix = _build_poisson_matrix(lambda_home, lambda_away)
    lambda_ht_h = lambda_home * ht_goal_share
    lambda_ht_a = lambda_away * ht_goal_share
    lambda_2h_h = lambda_home * (1 - ht_goal_share)
    lambda_2h_a = lambda_away * (1 - ht_goal_share)

    joint: dict[tuple[int, int, int, int], float] = {}
    ht_marginal: dict[tuple[int, int], float] = {}
    ft_marginal: dict[tuple[int, int], float] = {}

    for ht_h in range(MAX_GOALS + 1):
        for ht_a in range(MAX_GOALS + 1):
            p_ht = _poisson_pmf(ht_h, lambda_ht_h) * _poisson_pmf(ht_a, lambda_ht_a)
            if p_ht <= 0:
                continue
            for ft_h in range(ht_h, MAX_GOALS + 1):
                for ft_a in range(ht_a, MAX_GOALS + 1):
                    dh, da = ft_h - ht_h, ft_a - ht_a
                    p_2h = _poisson_pmf(dh, lambda_2h_h) * _poisson_pmf(da, lambda_2h_a)
                    p = p_ht * p_2h
                    if p <= 0:
                        continue
                    joint[(ht_h, ht_a, ft_h, ft_a)] = p
                    ht_marginal[(ht_h, ht_a)] = ht_marginal.get((ht_h, ht_a), 0.0) + p
                    ft_marginal[(ft_h, ft_a)] = ft_marginal.get((ft_h, ft_a), 0.0) + p

    total = sum(joint.values())
    if total > 0:
        joint = {k: v / total for k, v in joint.items()}
        ht_marginal = {k: v / total for k, v in ht_marginal.items()}
        ft_marginal = {k: v / total for k, v in ft_marginal.items()}

    sign_probs = _score_matrix_probs(ft_matrix)

    confidence = "medium" if match.odds.totals else "low"

    return ScorelineDistribution(
        joint=joint,
        ht_marginal=ht_marginal,
        ft_marginal=ft_marginal,
        sign_probs=sign_probs,
        source="poisson_h2h",
        confidence=confidence,
    )


def _distribution_from_dual_correct_score(
    ft_odds: dict[str, float],
    ht_odds: dict[str, float],
) -> ScorelineDistribution:
    """Joint HT/FT from separate full-time and half-time correct score markets (e.g. Betfair)."""
    ht_raw = proportional_devig(ht_odds)
    ft_raw = proportional_devig(ft_odds)

    ht_marginal: dict[tuple[int, int], float] = {
        tuple(int(x) for x in key.split("-")): prob for key, prob in ht_raw.items()
    }
    ft_marginal: dict[tuple[int, int], float] = {
        tuple(int(x) for x in key.split("-")): prob for key, prob in ft_raw.items()
    }

    joint: dict[tuple[int, int, int, int], float] = {}
    for (ht_h, ht_a), p_ht in ht_marginal.items():
        for (ft_h, ft_a), p_ft in ft_marginal.items():
            if ft_h < ht_h or ft_a < ht_a:
                continue
            key = (ht_h, ht_a, ft_h, ft_a)
            joint[key] = joint.get(key, 0.0) + p_ht * p_ft

    total = sum(joint.values())
    if total <= 0:
        raise ValueError("Dual correct score markets produced empty joint distribution")

    joint = {k: v / total for k, v in joint.items()}
    ht_marginal = {}
    ft_marginal_out: dict[tuple[int, int], float] = {}
    for (ht_h, ht_a, ft_h, ft_a), prob in joint.items():
        ht_marginal[(ht_h, ht_a)] = ht_marginal.get((ht_h, ht_a), 0.0) + prob
        ft_marginal_out[(ft_h, ft_a)] = ft_marginal_out.get((ft_h, ft_a), 0.0) + prob

    sign_probs = {"1": 0.0, "X": 0.0, "2": 0.0}
    for (ft_h, ft_a), prob in ft_marginal_out.items():
        sign_probs[fm_sign(ft_h, ft_a)] += prob

    return ScorelineDistribution(
        joint=joint,
        ht_marginal=ht_marginal,
        ft_marginal=ft_marginal_out,
        sign_probs=sign_probs,
        source="dual_correct_score",
        confidence="high",
    )


def build_distribution(match: MatchData, ht_goal_share: float = DEFAULT_HT_GOAL_SHARE) -> ScorelineDistribution:
    """Build HT/FT scoreline distribution using the best available odds."""
    if match.odds.ht_ft:
        return _distribution_from_ht_ft(match.odds.ht_ft)

    if match.odds.correct_score and match.odds.half_time_correct_score:
        return _distribution_from_dual_correct_score(
            match.odds.correct_score,
            match.odds.half_time_correct_score,
        )

    if match.odds.correct_score:
        return _distribution_from_correct_score(
            match.odds.correct_score,
            match.odds.ht_result or None,
            ht_goal_share,
        )

    if match.odds.h2h:
        return _distribution_from_poisson(match, ht_goal_share)

    raise ValueError("Insufficient odds to build scoreline distribution")
