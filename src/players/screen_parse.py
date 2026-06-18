"""Parse Fantamondiale FM app screenshots (OCR + heuristics)."""

from __future__ import annotations

import io
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from odds.api_normalize import TEAM_ALIASES, normalize_team
from players.models import MatchRoster, PlayerBonus
from scoring.lineup_rules import VICE_MIN_BONUS_GOAL

HOME_COL_MARKER = "__HOME_COL__"
AWAY_COL_MARKER = "__AWAY_COL__"

# Resize + Tesseract tuning (server-side speed)
OCR_MAX_SIDE = 1200
_OCR_MAX_CONCURRENT = 3
_ocr_semaphore = threading.Semaphore(_OCR_MAX_CONCURRENT)
_PLAYER_COL_WHITELIST = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789+-. "
    "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝàáâãäåæçèéêëìíîïñòóôõöøùúûüýÿ"
    "✓✔☑"
)


def _default_match_id(home: str, away: str) -> str:
    return f"{home[:3].upper()}-{away[:3].upper()}"


ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:POR|PORT(?:IERE)?|GK)\b", re.I), "GK"),
    (re.compile(r"\b(?:DIF|DIFENS(?:ORE)?|DEF)\b", re.I), "DEF"),
    (re.compile(r"\b(?:CEN|CENTRO(?:CAMPISTA)?|MID)\b", re.I), "MID"),
    (re.compile(r"\b(?:ATT|ATTACC(?:ANTE)?|FWD|A\/C)\b", re.I), "FWD"),
]

# FM app section headers (Italian)
SECTION_ROLE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"portier", re.I), "GK"),
    (re.compile(r"difensor", re.I), "DEF"),
    (re.compile(r"centrocamp", re.I), "MID"),
    (re.compile(r"attacc", re.I), "FWD"),
]

VICE_PATTERN = re.compile(r"[✓✔☑●◉◎]|vice", re.I)
BONUS_PATTERN = re.compile(r"\+(\d{1,2})")
# NOME +bonus (FM app: ERGASHEV +14, SUAREZ L. +5)
PLAYER_BONUS_RE = re.compile(
    r"([A-ZÀ-ÖØ-öø-ÿ][A-ZÀ-ÖØ-öø-ÿ\s.'·-]{0,26}?)\s+\+(\d{1,2})",
    re.I,
)
MATCH_IN_TEXT = re.compile(
    r"(?P<home>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s.'-]{2,30}?)"
    r"\s*(?:[-–—|·]|vs\.?)\s*"
    r"(?P<away>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s.'-]{2,30})",
    re.I,
)

SKIP_LINE = re.compile(
    r"^(scegli|scelta|calciatori|bonus|porta|gol|movimento|calciatori di|"
    r"portieri|attaccanti|centrocampisti|difensori|\(\+\)|\d{1,2}:\d{2}|"
    r"lun|mar|mer|gio|ven|sab|dom).*$",
    re.I,
)

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
    seen: dict[str, str] = {}
    for it_key, en_val in TEAM_ALIASES.items():
        seen[normalize_team(it_key)] = it_key.title() if it_key.islower() else it_key
        seen[normalize_team(en_val)] = TEAM_DISPLAY.get(en_val, en_val.title())
    for en, display in TEAM_DISPLAY.items():
        seen[normalize_team(en)] = display
    return sorted(seen.items(), key=lambda x: len(x[0]), reverse=True)


def _prepare_gray_image(data: bytes):
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    max_side = OCR_MAX_SIDE
    width, height = image.size
    if max(width, height) > max_side:
        scale = max_side / max(width, height)
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image, image.convert("L")


def _ocr_region(
    gray,
    box,
    *,
    psm: int = 6,
    lang: str = "ita+eng",
    whitelist: str | None = None,
) -> str:
    import pytesseract

    crop = gray.crop(box)
    crop = crop.point(lambda p: 255 if p > 140 else 0) if box[1] < gray.size[1] * 0.25 else crop
    config_parts = [f"--psm {psm}", "--oem 1"]
    if whitelist:
        config_parts.append(f"-c tessedit_char_whitelist={whitelist}")
    config = " ".join(config_parts)
    with _ocr_semaphore:
        try:
            return pytesseract.image_to_string(crop, lang=lang, config=config)
        except pytesseract.TesseractError:
            if lang != "eng":
                return pytesseract.image_to_string(crop, lang="eng", config=config)
            raise


def ocr_image_bytes(data: bytes, *, include_header: bool = True) -> str:
    """OCR FM screenshot: header banner + left (home) + right (away) columns."""
    try:
        import pytesseract  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "OCR non disponibile: installa Pillow e pytesseract (e Tesseract sul server)"
        ) from exc

    if len(data) > 5 * 1024 * 1024:
        raise ValueError("Screenshot troppo grande (max 5 MB ciascuno)")

    _image, gray = _prepare_gray_image(data)
    width, height = gray.size

    header_h = int(height * 0.20)
    body_top = int(height * 0.12)
    mid = width // 2
    gutter = max(8, width // 40)

    jobs: list[tuple[str, tuple[int, int, int, int], int, str, str | None]] = []
    if include_header:
        jobs.append(("header", (0, 0, width, header_h), 7, "ita+eng", None))
    jobs.extend(
        [
            (
                "home",
                (0, body_top, mid - gutter, height),
                6,
                "eng",
                _PLAYER_COL_WHITELIST,
            ),
            (
                "away",
                (mid + gutter, body_top, width, height),
                6,
                "eng",
                _PLAYER_COL_WHITELIST,
            ),
        ]
    )

    results: dict[str, str] = {}
    workers = min(_OCR_MAX_CONCURRENT, len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            name: pool.submit(_ocr_region, gray, box, psm=psm, lang=lang, whitelist=wl)
            for name, box, psm, lang, wl in jobs
        }
        for name, future in futures.items():
            results[name] = future.result().strip()

    header_text = results.get("header", "")
    home_col = results.get("home", "")
    away_col = results.get("away", "")

    return (
        f"{header_text}\n{HOME_COL_MARKER}\n{home_col}\n"
        f"{AWAY_COL_MARKER}\n{away_col}"
    )


def ocr_images(images: list[bytes]) -> str:
    if len(images) > 6:
        raise ValueError("Massimo 6 screenshot per analisi")
    blobs = [b for b in images if b]
    if not blobs:
        return ""
    parts: list[str] = []
    parts.append(ocr_image_bytes(blobs[0], include_header=True).strip())
    for blob in blobs[1:]:
        parts.append(ocr_image_bytes(blob, include_header=False).strip())
    return "\n\n".join(p for p in parts if p)


def _detect_role(fragment: str) -> str | None:
    for pattern, role in ROLE_PATTERNS:
        if pattern.search(fragment):
            return role
    return None


def _find_team_in_text(fragment: str) -> str | None:
    lower = fragment.lower()
    for token, display in _known_team_tokens():
        if len(token) >= 4 and token in lower:
            return display
    for it_key, en_val in TEAM_ALIASES.items():
        if len(it_key) >= 4 and it_key in lower:
            return TEAM_DISPLAY.get(en_val, it_key.title())
    return None


def _find_teams_by_position(text: str) -> list[str]:
    """All known NT names found in text, ordered by first appearance."""
    lower = text.lower()
    hits: list[tuple[int, str]] = []
    seen: set[str] = set()

    candidates: list[tuple[str, str]] = list(_known_team_tokens())
    for it_key, en_val in TEAM_ALIASES.items():
        display = TEAM_DISPLAY.get(en_val, it_key.title())
        candidates.append((it_key, display))

    for token, display in sorted(candidates, key=lambda x: len(x[0]), reverse=True):
        if len(token) < 4:
            continue
        idx = lower.find(token)
        if idx < 0:
            continue
        norm = normalize_team(display)
        if norm in seen:
            continue
        seen.add(norm)
        hits.append((idx, display))

    hits.sort(key=lambda item: item[0])
    return [name for _, name in hits]


def extract_match_teams(text: str) -> tuple[str, str]:
    """Home and away from OCR text (FM banner: UZBEKISTAN – COLOMBIA)."""
    compact = " ".join(text.split())

    header = compact[:600]
    for match in MATCH_IN_TEXT.finditer(header):
        home = _find_team_in_text(match.group("home")) or match.group("home").strip().title()
        away_raw = match.group("away")
        away = _find_team_in_text(away_raw) or away_raw.strip().title()
        if normalize_team(home) != normalize_team(away):
            return home, away

    found = _find_teams_by_position(text)
    if len(found) >= 2:
        return found[0], found[1]

    raise ValueError(
        "Non riesco a leggere casa/ospite dagli screenshot. "
        "Includi lo screen con il banner partita in alto (es. UZBEKISTAN – COLOMBIA)."
    )


def _clean_player_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw).strip(" .-|·")
    name = re.sub(r"^[O0○◯]\s*", "", name)
    if len(name) < 2:
        return ""
    parts = name.split()
    if len(parts) >= 2 and len(parts[-1]) <= 2 and parts[-1].replace(".", "").isalpha():
        pass  # keep suffix e.g. "L." in Suarez L.
    return name.upper() if name.isupper() else _format_player_name(name)


def _format_player_name(raw: str) -> str:
    parts = raw.split()
    if not parts:
        return raw
    return " ".join(p[:1].upper() + p[1:].lower() if len(p) > 1 else p.upper() for p in parts)


def _is_vice_line(line: str) -> bool:
    return bool(VICE_PATTERN.search(line))


def _parse_player_entries(line: str, role: str) -> list[tuple[str, int, int, bool]]:
    """Return list of (name, bonus_goal, bonus_cs, is_vice) on one OCR line."""
    if SKIP_LINE.match(line.strip()):
        return []

    matches = list(PLAYER_BONUS_RE.finditer(line))
    if not matches:
        return []

    entries: list[tuple[str, int, int, bool]] = []
    for idx, match in enumerate(matches):
        name = _clean_player_name(match.group(1))
        if not name or len(name) < 3:
            continue
        if name.lower() in {"bonus", "porta", "gol", "fatto", "inviolata"}:
            continue
        bonus = int(match.group(2))
        bonus_cs = bonus if role == "GK" else 0
        tail = line[match.end() : match.end() + 8]
        is_vice = bool(VICE_PATTERN.search(tail)) or (
            bool(VICE_PATTERN.search(line)) and idx == len(matches) - 1
        )
        if " vice" in line.lower() and idx == len(matches) - 1:
            is_vice = True
        entries.append((name, bonus, bonus_cs, is_vice))

    return entries


def _add_player(
    players: list[PlayerBonus],
    seen: set[tuple[str, str]],
    *,
    name: str,
    side: str,
    role: str,
    bonus_goal: int,
    bonus_cs: int,
    is_vice: bool,
) -> None:
    key = (name.lower(), side)
    if key in seen:
        return
    seen.add(key)
    players.append(
        PlayerBonus(
            name=name,
            side=side,
            role=role,
            bonus_goal=bonus_goal,
            bonus_clean_sheet=bonus_cs,
            vice_allenatore=is_vice,
        )
    )


def _balance_player_sides(players: list[PlayerBonus]) -> list[PlayerBonus]:
    """If OCR missed away column, split each role group in half (home | away)."""
    if any(p.side == "away" for p in players):
        return players

    by_role: dict[str, list[PlayerBonus]] = {}
    for player in players:
        by_role.setdefault(player.role, []).append(player)

    for group in by_role.values():
        if len(group) < 2:
            continue
        split = len(group) // 2
        for idx, player in enumerate(group):
            if player.vice_allenatore:
                continue
            player.side = "home" if idx < split else "away"

    return players


def _validate_roster_sides(players: list[PlayerBonus]) -> None:
    pool = [p for p in players if not p.vice_allenatore]
    home = sum(1 for p in pool if p.side == "home")
    away = sum(1 for p in pool if p.side == "away")
    if home >= 2 and away >= 2:
        return
    raise ValueError(
        f"Giocatori letti: {home} casa, {away} ospite — servono almeno 2 per squadra. "
        "Carica screen nitidi con entrambe le colonne (Uzbekistan a sinistra, Colombia a destra)."
    )


def extract_players(text: str, home: str, away: str) -> list[PlayerBonus]:
    """Parse FM player rows: two columns (home left, away right) under section headers."""
    current_role = "MID"
    forced_side: str | None = None
    section_row = 0
    players: list[PlayerBonus] = []
    seen: set[tuple[str, str]] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line == HOME_COL_MARKER:
            forced_side = "home"
            section_row = 0
            continue
        if line == AWAY_COL_MARKER:
            forced_side = "away"
            section_row = 0
            continue

        for pattern, role in SECTION_ROLE:
            if pattern.search(line) and not PLAYER_BONUS_RE.search(line):
                current_role = role
                section_row = 0
                break
        else:
            entries = _parse_player_entries(line, current_role)
            if not entries:
                continue

            if len(entries) >= 2:
                sides = ["home", "away"]
            elif forced_side:
                sides = [forced_side]
            else:
                sides = ["home" if section_row % 2 == 0 else "away"]
                section_row += 1

            for entry, side in zip(entries, sides, strict=False):
                name, bonus_goal, bonus_cs, is_vice = entry
                _add_player(
                    players,
                    seen,
                    name=name,
                    side=side,
                    role=current_role,
                    bonus_goal=bonus_goal,
                    bonus_cs=bonus_cs,
                    is_vice=is_vice,
                )

    if len(players) < 4:
        raise ValueError(
            f"Letti solo {len(players)} giocatori dagli screenshot (servono almeno 4 oltre al vice). "
            "Carica tutti gli screen bonus con Portieri, Attaccanti, Centrocampisti."
        )

    players = _balance_player_sides(players)
    _validate_roster_sides(players)
    return players


def _ensure_single_vice(players: list[PlayerBonus]) -> None:
    vices = [p for p in players if p.vice_allenatore]
    if len(vices) > 1:
        raise ValueError("Più di un vice allenatore rilevato negli screenshot")
    if len(vices) == 1 and vices[0].bonus_goal < VICE_MIN_BONUS_GOAL:
        raise ValueError(
            f"Vice {vices[0].name}: bonus gol {vices[0].bonus_goal} < {VICE_MIN_BONUS_GOAL}"
        )


def roster_from_ocr_text(text: str) -> MatchRoster:
    home, away = extract_match_teams(text)
    players = extract_players(text, home, away)
    _ensure_single_vice(players)

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
