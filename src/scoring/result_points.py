"""Fantamondiale daily result scoring rules (H, I, J, superbonus)."""

from __future__ import annotations

MAX_GOALS = 9


def fm_sign(home: int, away: int) -> str:
    """Return 1/X/2 sign for a full-time score."""
    if home > away:
        return "1"
    if home == away:
        return "X"
    return "2"


def fm_points_if_correct(
    ht_home: int,
    ht_away: int,
    ft_home: int,
    ft_away: int,
) -> dict[str, int | str]:
    """
    Payoffs awarded when HT/FT predictions are all correct.

    Rules (regolamento §8.2):
    - H: exact HT score — +4 (+2 if 0-0)
    - I: exact FT score (regular time) — +8 (+6 if 0-0)
    - J: 1/X/2 sign at FT — +2 (auto-derived from I)
    - Superbonus: H + I + J all correct — +12 (+8 if FT 0-0)
    """
    if not (0 <= ht_home <= MAX_GOALS and 0 <= ht_away <= MAX_GOALS):
        raise ValueError(f"HT goals must be between 0 and {MAX_GOALS}")
    if not (0 <= ft_home <= MAX_GOALS and 0 <= ft_away <= MAX_GOALS):
        raise ValueError(f"FT goals must be between 0 and {MAX_GOALS}")
    if ft_home < ht_home or ft_away < ht_away:
        raise ValueError("FT score cannot have fewer goals than HT score")

    ht_is_nil = ht_home == 0 and ht_away == 0
    ft_is_nil = ft_home == 0 and ft_away == 0

    h_pts = 2 if ht_is_nil else 4
    i_pts = 6 if ft_is_nil else 8
    j_pts = 2
    superbonus_pts = 8 if ft_is_nil else 12

    return {
        "h_pts": h_pts,
        "i_pts": i_pts,
        "j_pts": j_pts,
        "superbonus_pts": superbonus_pts,
        "total_if_all_hit": h_pts + i_pts + j_pts + superbonus_pts,
        "sign": fm_sign(ft_home, ft_away),
    }
