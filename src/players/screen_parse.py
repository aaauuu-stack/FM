"""Parse Fantamondiale FM app screenshots (OCR + heuristics)."""

from __future__ import annotations

import io
import re
import threading
from concurrent.futures import ThreadPoolExecutor

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
_BANNER_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ-–— "
_BANNER_MIN_BRIGHTNESS = 160
_BANNER_UPSCALE_WIDTH = 900
_BANNER_MIN_SCORE = 900.0


def _default_match_id(home: str, away: str) -> str:
    return f"{home[:3].upper()}-{away[:3].upper()}"


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
MATCH_LOOSE = re.compile(
    r"\b(?P<home>[A-ZÀ-ÖØ-Þ]{4,24})\s+(?:[-–—]\s*)?(?P<away>[A-ZÀ-ÖØ-Þ]{4,24})\b"
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


def _row_brightness(gray, y: int) -> float:
    width, _ = gray.size
    pixels = gray.crop((0, y, width, y + 1)).tobytes()
    return sum(pixels) / max(len(pixels), 1)


def _banner_strip_score(gray) -> float:
    """Score how likely the top of the image contains the FM match banner."""
    _, height = gray.size
    scan_h = int(height * 0.32)
    y = 0
    best = 0.0

    while y < scan_h:
        while y < scan_h and _row_brightness(gray, y) < _BANNER_MIN_BRIGHTNESS:
            y += 1
        start = y
        while y < scan_h and _row_brightness(gray, y) >= _BANNER_MIN_BRIGHTNESS - 15:
            y += 1
        end = y
        band_h = end - start
        if band_h >= 6:
            avg = sum(_row_brightness(gray, row_y) for row_y in range(start, end)) / band_h
            best = max(best, band_h * avg)
    return best


def _detect_banner_box(gray) -> tuple[int, int, int, int]:
    """Locate the bright FM match banner (e.g. UZBEKISTAN - COLOMBIA)."""
    width, height = gray.size
    scan_h = int(height * 0.32)
    y = 0
    best: tuple[int, int, float] | None = None

    while y < scan_h:
        while y < scan_h and _row_brightness(gray, y) < _BANNER_MIN_BRIGHTNESS:
            y += 1
        start = y
        while y < scan_h and _row_brightness(gray, y) >= _BANNER_MIN_BRIGHTNESS - 15:
            y += 1
        end = y
        band_h = end - start
        if band_h >= 6:
            avg = sum(_row_brightness(gray, row_y) for row_y in range(start, end)) / band_h
            score = band_h * avg
            if best is None or score > best[2]:
                best = (start, end, score)

    if best is not None:
        top = max(0, best[0] - 2)
        bottom = min(height, best[1] + 2)
        return (0, top, width, bottom)

    top = int(height * 0.11)
    bottom = int(height * 0.19)
    return (0, top, width, bottom)


def _pick_banner_image_index(blobs: list[bytes]) -> int | None:
    """Index of the screenshot most likely to contain the match banner."""
    if not blobs:
        return None
    scores = [_banner_strip_score(_prepare_gray_image(blob)[1]) for blob in blobs]
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    if scores[best_idx] < _BANNER_MIN_SCORE:
        return None
    return best_idx


def _prepare_banner_for_ocr(crop):
    from PIL import Image, ImageOps

    crop = ImageOps.autocontrast(crop)
    width, height = crop.size
    if width < _BANNER_UPSCALE_WIDTH:
        scale = _BANNER_UPSCALE_WIDTH / width
        crop = crop.resize(
            (int(width * scale), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    return crop


def _ocr_region(
    gray,
    box,
    *,
    psm: int = 6,
    lang: str = "ita+eng",
    whitelist: str | None = None,
    enhance: bool = False,
    banner: bool = False,
) -> str:
    import pytesseract
    from PIL import ImageOps

    crop = gray.crop(box)
    if banner:
        crop = _prepare_banner_for_ocr(crop)
    elif enhance:
        crop = ImageOps.autocontrast(crop)
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

    banner_box = _detect_banner_box(gray) if include_header else None
    if include_header and banner_box is not None:
        body_top = min(height, banner_box[3] + max(8, int(height * 0.01)))
        header_h = max(banner_box[3] + 4, int(height * 0.12))
    else:
        body_top = int(height * 0.02)
        header_h = int(height * 0.12)
    mid = width // 2
    gutter = max(8, width // 40)

    jobs: list[tuple[str, tuple[int, int, int, int], int, str, str | None, bool, bool]] = []
    if include_header and banner_box is not None:
        jobs.append(("header", (0, 0, width, header_h), 7, "ita+eng", None, False, False))
        jobs.append(("banner", banner_box, 7, "eng", _BANNER_WHITELIST, False, True))
    jobs.extend(
        [
            (
                "home",
                (0, body_top, mid - gutter, height),
                6,
                "eng",
                _PLAYER_COL_WHITELIST,
                False,
                False,
            ),
            (
                "away",
                (mid + gutter, body_top, width, height),
                6,
                "eng",
                _PLAYER_COL_WHITELIST,
                False,
                False,
            ),
        ]
    )

    results: dict[str, str] = {}
    workers = min(_OCR_MAX_CONCURRENT, len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            name: pool.submit(
                _ocr_region,
                gray,
                box,
                psm=psm,
                lang=lang,
                whitelist=wl,
                enhance=enh,
                banner=is_banner,
            )
            for name, box, psm, lang, wl, enh, is_banner in jobs
        }
        for name, future in futures.items():
            results[name] = future.result().strip()

    header_parts = [results.get("header", ""), results.get("banner", "")]
    header_text = "\n".join(part for part in header_parts if part)
    home_col = results.get("home", "")
    away_col = results.get("away", "")

    return (
        (f"{header_text}\n" if header_text else "")
        + f"{HOME_COL_MARKER}\n{home_col}\n"
        f"{AWAY_COL_MARKER}\n{away_col}"
    )


def ocr_images(images: list[bytes]) -> str:
    if len(images) > 6:
        raise ValueError("Massimo 6 screenshot per analisi")
    blobs = [b for b in images if b]
    if not blobs:
        return ""

    banner_idx = _pick_banner_image_index(blobs)
    ocr_all_headers = banner_idx is None

    indexed: list[tuple[int, str]] = []
    for i, blob in enumerate(blobs):
        with_header = ocr_all_headers or i == banner_idx
        text = ocr_image_bytes(blob, include_header=with_header).strip()
        if text:
            indexed.append((i, text))

    if not indexed:
        return ""

    if banner_idx is not None:
        ordered = [part for idx, part in indexed if idx == banner_idx]
        ordered.extend(part for idx, part in indexed if idx != banner_idx)
    else:
        ordered = [part for _, part in indexed]

    return "\n\n".join(ordered)


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


def _resolve_team_pair(home_raw: str, away_raw: str) -> tuple[str, str] | None:
    home_known = _find_team_in_text(home_raw)
    away_known = _find_team_in_text(away_raw)
    if not home_known and not away_known:
        return None
    home = home_known or home_raw.strip().title()
    away = away_known or away_raw.strip().title()
    if normalize_team(home) == normalize_team(away):
        return None
    return home, away


def extract_match_teams(text: str) -> tuple[str, str]:
    """Home and away from OCR text (FM banner: UZBEKISTAN – COLOMBIA)."""
    compact = " ".join(text.split())
    header = compact[:800]

    for pattern in (MATCH_IN_TEXT, MATCH_LOOSE):
        for match in pattern.finditer(header):
            pair = _resolve_team_pair(match.group("home"), match.group("away"))
            if pair:
                return pair

    if HOME_COL_MARKER in text:
        pre_col = text.split(HOME_COL_MARKER, 1)[0]
        pre_compact = " ".join(pre_col.split())
        for pattern in (MATCH_IN_TEXT, MATCH_LOOSE):
            for match in pattern.finditer(pre_compact):
                pair = _resolve_team_pair(match.group("home"), match.group("away"))
                if pair:
                    return pair

    found = _find_teams_by_position(text)
    if len(found) >= 2:
        return found[0], found[1]

    snippet = compact[:120].strip()
    raise ValueError(
        "Non riesco a leggere casa/ospite dagli screenshot. "
        "Includi lo screen con il banner partita in alto (es. UZBEKISTAN – COLOMBIA)."
        + (f" OCR banner: «{snippet}»" if snippet else "")
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
