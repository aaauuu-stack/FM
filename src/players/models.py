"""Player roster models for Fantamondiale lineup (Phase 2)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class PlayerBonus:
    """FM bonus values from app screenshots for one player."""

    name: str
    side: str  # "home" or "away"
    role: str  # GK, DEF, MID, FWD
    bonus_goal: int = 0
    bonus_clean_sheet: int = 0  # GK: porta inviolata (bonus variabile)
    starter: bool = False  # inferito da SofaScore / euristica (FM non indica titolari)
    vice_allenatore: bool = False  # 5° giocatore pre-selezionato dallo screen
    book_goal_matched: bool = False  # trovato su mercato anytime gol
    book_card_matched: bool = False  # trovato su mercato cartellini
    p_goal: float | None = None
    p_gk_goal: float | None = None
    p_penalty_scored: float | None = None
    p_penalty_missed: float | None = None
    p_penalty_saved: float | None = None
    p_yellow: float | None = None
    p_red: float | None = None
    p_own_goal: float | None = None
    p_clean_sheet: float | None = None

    @property
    def is_goalkeeper(self) -> bool:
        return self.role.upper() == "GK"

    @property
    def is_defender(self) -> bool:
        return self.role.upper() == "DEF"

    def with_probs(self, **kwargs) -> PlayerBonus:
        """Return a copy with updated probability fields."""
        return replace(self, **kwargs)


@dataclass
class MatchRoster:
    """All selectable players for one FM match."""

    match_id: str
    home: str
    away: str
    kickoff: str = ""
    players: list[PlayerBonus] = field(default_factory=list)

    def home_players(self) -> list[PlayerBonus]:
        return [p for p in self.players if p.side == "home"]

    def away_players(self) -> list[PlayerBonus]:
        return [p for p in self.players if p.side == "away"]

    def vice_player(self) -> PlayerBonus | None:
        marked = [p for p in self.players if p.vice_allenatore]
        if not marked:
            return None
        if len(marked) > 1:
            raise ValueError(
                "Un solo giocatore puo essere vice_allenatore: "
                + ", ".join(p.name for p in marked)
            )
        return marked[0]

    def lineup_pool(self) -> list[PlayerBonus]:
        """Giocatori disponibili per i 4 slot (escluso vice, solo titolari)."""
        return [
            p for p in self.players if not p.vice_allenatore and p.starter
        ]
