"""Expected value engine for Fantamondiale result predictions."""

from __future__ import annotations

from dataclasses import dataclass

from odds.distribution import ScorelineDistribution, build_distribution
from odds.match_loader import MatchData
from scoring.result_points import fm_points_if_correct, fm_sign


@dataclass
class ResultRecommendation:
    ht_home: int
    ht_away: int
    ft_home: int
    ft_away: int
    sign: str
    p_ht_exact: float
    p_ft_exact: float
    p_sign: float
    p_superbonus: float
    h_pts: int
    i_pts: int
    j_pts: int
    superbonus_pts: int
    ev_total: float
    ev_breakdown: dict[str, float]


def _prob_sign(sign: str, dist: ScorelineDistribution) -> float:
    return dist.sign_probs.get(sign, 0.0)


def _prob_ht_exact(ht_h: int, ht_a: int, dist: ScorelineDistribution) -> float:
    return dist.ht_marginal.get((ht_h, ht_a), 0.0)


def _prob_ft_exact(ft_h: int, ft_a: int, dist: ScorelineDistribution) -> float:
    return dist.ft_marginal.get((ft_h, ft_a), 0.0)


def _prob_superbonus(ht_h: int, ht_a: int, ft_h: int, ft_a: int, dist: ScorelineDistribution) -> float:
    return dist.joint.get((ht_h, ht_a, ft_h, ft_a), 0.0)


def compute_ev(
    ht_h: int,
    ht_a: int,
    ft_h: int,
    ft_a: int,
    dist: ScorelineDistribution,
) -> ResultRecommendation:
    """Compute FM expected value for a specific HT/FT prediction."""
    payoffs = fm_points_if_correct(ht_h, ht_a, ft_h, ft_a)
    sign = str(payoffs["sign"])

    p_ht = _prob_ht_exact(ht_h, ht_a, dist)
    p_ft = _prob_ft_exact(ft_h, ft_a, dist)
    p_sign = _prob_sign(sign, dist)
    p_super = _prob_superbonus(ht_h, ht_a, ft_h, ft_a, dist)

    h_pts = int(payoffs["h_pts"])
    i_pts = int(payoffs["i_pts"])
    j_pts = int(payoffs["j_pts"])
    super_pts = int(payoffs["superbonus_pts"])

    ev_h = p_ht * h_pts
    ev_i = p_ft * i_pts
    ev_j = p_sign * j_pts
    ev_super = p_super * super_pts
    ev_total = ev_h + ev_i + ev_j + ev_super

    return ResultRecommendation(
        ht_home=ht_h,
        ht_away=ht_a,
        ft_home=ft_h,
        ft_away=ft_a,
        sign=sign,
        p_ht_exact=p_ht,
        p_ft_exact=p_ft,
        p_sign=p_sign,
        p_superbonus=p_super,
        h_pts=h_pts,
        i_pts=i_pts,
        j_pts=j_pts,
        superbonus_pts=super_pts,
        ev_total=ev_total,
        ev_breakdown={
            "h": ev_h,
            "i": ev_i,
            "j": ev_j,
            "superbonus": ev_super,
        },
    )


def _iter_candidates(dist: ScorelineDistribution) -> set[tuple[int, int, int, int]]:
    """All valid HT/FT candidates from the distribution support."""
    if dist.joint:
        return set(dist.joint.keys())

    candidates: set[tuple[int, int, int, int]] = set()
    for (ht_h, ht_a) in dist.ht_marginal:
        for (ft_h, ft_a) in dist.ft_marginal:
            if ft_h >= ht_h and ft_a >= ht_a:
                candidates.add((ht_h, ht_a, ft_h, ft_a))
    return candidates


def rank_predictions(
    match: MatchData,
    top_n: int = 5,
    ht_goal_share: float = 0.45,
) -> tuple[ScorelineDistribution, list[ResultRecommendation]]:
    """Rank all candidate scorelines by FM expected value."""
    dist = build_distribution(match, ht_goal_share)
    candidates = _iter_candidates(dist)

    recommendations = [
        compute_ev(ht_h, ht_a, ft_h, ft_a, dist)
        for ht_h, ht_a, ft_h, ft_a in candidates
    ]
    recommendations.sort(key=lambda r: r.ev_total, reverse=True)

    return dist, recommendations[:top_n]


def most_probable_prediction(
    dist: ScorelineDistribution,
) -> ResultRecommendation | None:
    """Naive baseline: pick the scoreline with highest joint probability."""
    if not dist.joint:
        return None
    best_key = max(dist.joint, key=dist.joint.get)
    ht_h, ht_a, ft_h, ft_a = best_key
    return compute_ev(ht_h, ht_a, ft_h, ft_a, dist)


def format_score(h: int, a: int) -> str:
    return f"{h}-{a}"
