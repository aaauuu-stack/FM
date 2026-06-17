"""Parse Fantamondiale FM app screenshots (OCR + heuristics)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from odds.api_normalize import TEAM_ALIASES, normalize_team
from players.models import MatchRoster, PlayerBonus
from scoring.lineup_rules import VICE_MIN_BONUS_GOAL


def _default_match_id(home: str, away: str) -> str:
    return f"{home[:3].upper()}-{away[:3].upper()}"

ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:POR|PORT(?:IERE)?|GK)\b", re.I), "GK"),
    (re.compile(r"\b(?:DIF|DIFENS(?:ORE)?|DEF)\b", re.I), "DEF"),
    (re.compile(r"\b(?:CEN|CENTRO(?:CAMPISTA)?|MID)\b", re.I), "MID"),
    (re.compile(r"\b(?:ATT|ATTACC(?:ANTE)?|FWD|A\/C)\b", re.I), "FWD"),
]

VICE_PATTERN = re.compile(r"[✓✔☑]|vice", re.I)
BONUS_PATTERN = re.compile(r"\+(\d{1,2})")
MATCH_LINE = re.compile(
    r"^\s*(?P<home>.+?)\s*(?:[-–—]|vs\.?|×|x)\s*(?P<away>.+?)\s*$",
    re.I,
)

# Italian display names for WC teams (extend as needed)
TEAM_DISPLAY: dict[str, str] = {
    "england": "Inghilterra",
    "croatia": "Croazia",
    "france": "Francia",
    "brazil": "Brasile",
    "germany": "Germania",
    "scotland": "Scozia",
    "spain": "Spagna",
    "italy": "Italia",
    "colombia": "Colombia",
    "uzbekistan": "Uzbekistan",
    "mexico": "Messico",
    "usa": "USA",
    "japan": "Giappone",
    "south korea": "Corea del Sud",
    "netherlands": "Olanda",
    "portugal": "Portogallo",
    "belgium": "Belgio",
    "argentina": "Argentina",
    "uruguay": "Uruguay",
}


def _known_team_tokens() -> list[tuple[str, str]]:
    """Return (normalized_key, display_name) sorted longest first."""
    seen: dict[str, str] = {}
    for it_key, en_val in TEAM_ALIASES.items():
        seen[normalize_team(it_key)] = it_key.title() if it_key.islower() else it_key
        seen[normalize_team(en_val)] = TEAM_DISPLAY.get(en_val, en_val.title())
    for en, display in TEAM_DISPLAY.items():
        seen[normalize_team(en)] = display
    return sorted(seen.items(), key=lambda x: len(x[0]), reverse=True)


def ocr_image_bytes(data: bytes) -> str:
    """Run Tesseract OCR on one screenshot."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "OCR non disponibile: installa Pillow e pytesseract (e Tesseract sul server)"
        ) from exc

    image = Image.open(io.BytesIO(data))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return pytesseract.image_to_string(image, lang="ita+eng")


def ocr_images(images: list[bytes]) -> str:
    parts = [ocr_image_bytes(blob).strip() for blob in images if blob]
    return "\n\n".join(p for p in parts if p)


def _detect_role(fragment: str) -> str | None:
    for pattern, role in ROLE_PATTERNS:
        if pattern.search(fragment):
            return role
    return None


def _find_team_in_line(line: str) -> str | None:
    norm_line = normalize_team(line)
    for token, display in _known_team_tokens():
        if token and token in norm_line:
            return display
    return None


def extract_match_teams(text: str) -> tuple[str, str]:
    """Home and away from OCR text (Italian or English names)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    for line in lines[:40]:
        match = MATCH_LINE.match(line)
        if match:
            home = _find_team_in_line(match.group("home")) or match.group("home").strip()
            away = _find_team_in_line(match.group("away")) or match.group("away").strip()
            if home and away and normalize_team(home) != normalize_team(away):
                return home, away

    found: list[str] = []
    seen_norm: set[str] = set()
    for line in lines[:50]:
        team = _find_team_in_line(line)
        if team:
            norm = normalize_team(team)
            if norm not in seen_norm:
                seen_norm.add(norm)
                found.append(team)

    if len(found) >= 2:
        return found[0], found[1]

    raise ValueError(
        "Non riesco a leggere casa/ospite dagli screenshot. "
        "Assicurati che compaiano i nomi delle squadre (es. Uzbekistan - Colombia)."
    )


def _parse_player_line(line: str) -> dict | None:
    bonuses = [int(x) for x in BONUS_PATTERN.findall(line)]
    if not bonuses:
        return None

    role = _detect_role(line)
    if not role:
        return None

    is_vice = bool(VICE_PATTERN.search(line))
    cleaned = BONUS_PATTERN.sub(" ", line)
    for pat, _ in ROLE_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    cleaned = VICE_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ\s'.-]", " ", cleaned)
    name = re.sub(r"\s+", " ", cleaned).strip(" .-")
    if len(name) < 2:
        return None

    bonus_goal = bonuses[0]
    bonus_cs = bonuses[1] if len(bonuses) > 1 and role in {"GK", "DEF"} else 0

    return {
        "name": _format_player_name(name),
        "role": role,
        "bonus_goal": bonus_goal,
        "bonus_clean_sheet": bonus_cs,
        "vice_allenatore": is_vice,
    }


def _format_player_name(raw: str) -> str:
    parts = raw.split()
    if not parts:
        return raw
    if len(parts) >= 2 and len(parts[-1]) <= 2 and parts[-1].isupper():
        parts = parts[:-1]
    return " ".join(p[:1].upper() + p[1:].lower() if len(p) > 1 else p.upper() for p in parts)


def extract_players(text: str, home: str, away: str) -> list[PlayerBonus]:
    """Parse player rows; assign side by team section headers in OCR text."""
    home_norm = normalize_team(home)
    away_norm = normalize_team(away)
    current_side = "home"
    players: list[PlayerBonus] = []
    seen: set[tuple[str, str]] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        team_hit = _find_team_in_line(line)
        if team_hit:
            norm = normalize_team(team_hit)
            if norm == home_norm:
                current_side = "home"
                continue
            if norm == away_norm:
                current_side = "away"
                continue

        parsed = _parse_player_line(line)
        if not parsed:
            continue

        key = (parsed["name"].lower(), current_side)
        if key in seen:
            continue
        seen.add(key)

        players.append(
            PlayerBonus(
                name=parsed["name"],
                side=current_side,
                role=parsed["role"],
                bonus_goal=parsed["bonus_goal"],
                bonus_clean_sheet=parsed["bonus_clean_sheet"],
                vice_allenatore=parsed["vice_allenatore"],
            )
        )

    if len(players) < 4:
        raise ValueError(
            f"Letti solo {len(players)} giocatori dagli screenshot (servono almeno 4 oltre al vice). "
            "Carica tutti gli screen bonus della partita."
        )

    return players


def roster_from_ocr_text(text: str) -> MatchRoster:
    home, away = extract_match_teams(text)
    players = extract_players(text, home, away)

    vice = [p for p in players if p.vice_allenatore]
    if len(vice) > 1:
        raise ValueError("Più di un vice allenatore rilevato negli screenshot")
    if vice and vice[0].bonus_goal < VICE_MIN_BONUS_GOAL:
        raise ValueError(
            f"Vice {vice[0].name}: bonus gol {vice[0].bonus_goal} < {VICE_MIN_BONUS_GOAL}"
        )

    return MatchRoster(
        match_id=_default_match_id(home, away),
        home=home,
        away=away,
        players=players,
    )


def roster_from_screenshots(images: list[bytes]) -> MatchRoster:
    if not images:
        raise ValueError("Carica almeno uno screenshot FM")
    text = ocr_images(images)
    if not text.strip():
        raise ValueError("OCR vuoto — screenshot illeggibili o troppo sfocati")
    return roster_from_ocr_text(text)


@dataclass
class ParsePreview:
    home: str
    away: str
    player_count: int
    vice_name: str | None
    ocr_excerpt: str


def preview_parse(text: str, *, excerpt_len: int = 400) -> ParsePreview:
    roster = roster_from_ocr_text(text)
    vice = roster.vice_player()
    return ParsePreview(
        home=roster.home,
        away=roster.away,
        player_count=len(roster.players),
        vice_name=vice.name if vice else None,
        ocr_excerpt=text[:excerpt_len].replace("\n", " | "),
    )
