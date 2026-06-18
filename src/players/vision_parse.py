"""Read FM screenshots with a vision model (same approach as ChatGPT)."""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from players.models import MatchRoster, PlayerBonus
from players.screen_parse import _default_match_id, _ensure_single_vice, _validate_roster_sides
from scoring.lineup_rules import VICE_MIN_BONUS_GOAL

VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")
_MAX_IMAGES = 6

_SYSTEM_PROMPT = """\
You extract Fantamondiale (FM) mobile app roster data from screenshots.
Return ONLY valid JSON (no markdown fences) with this schema:
{
  "home": "Home team display name",
  "away": "Away team display name",
  "players": [
    {
      "name": "Player Name",
      "side": "home" or "away",
      "role": "GK" | "DEF" | "MID" | "FWD",
      "bonus_goal": integer,
      "bonus_clean_sheet": integer (GK only, else 0),
      "vice": boolean (true if marked vice allenatore / checkmark)
    }
  ]
}
Rules:
- Match banner at top shows HOME – AWAY (home = left column in player lists).
- Section headers: Portieri=GK, Difensori=DEF, Centrocampisti=MID, Attaccanti=FWD.
- bonus_goal is the +N goal bonus; GK rows may also show clean-sheet bonus.
- Include every visible player across all screenshots; merge duplicates once.
- FM lists the full selectable squad (starters and bench) — do NOT guess who starts.
- Use Italian display names when shown (e.g. Uzbekistan, Colombia, Inghilterra).
"""


def vision_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def _guess_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _normalize_role(raw: str) -> str:
    role = raw.strip().upper()
    mapping = {
        "GK": "GK",
        "GOALKEEPER": "GK",
        "PORTIERE": "GK",
        "PORTIERI": "GK",
        "DEF": "DEF",
        "DEFENDER": "DEF",
        "DIFENSORE": "DEF",
        "DIFENSORI": "DEF",
        "MID": "MID",
        "MIDFIELDER": "MID",
        "CENTROCAMPISTA": "MID",
        "CENTROCAMPISTI": "MID",
        "FWD": "FWD",
        "FORWARD": "FWD",
        "ATTACCANTE": "FWD",
        "ATTACCANTI": "FWD",
    }
    return mapping.get(role, role if role in {"GK", "DEF", "MID", "FWD"} else "MID")


def roster_from_vision_data(data: dict[str, Any]) -> MatchRoster:
    """Build MatchRoster from vision model JSON."""
    home = str(data.get("home", "")).strip()
    away = str(data.get("away", "")).strip()
    if not home or not away:
        raise ValueError("Vision: mancano casa/ospite nel JSON")

    players: list[PlayerBonus] = []
    seen: set[tuple[str, str]] = set()
    for row in data.get("players") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        side = str(row.get("side", "")).strip().lower()
        if not name or side not in {"home", "away"}:
            continue
        key = (name.lower(), side)
        if key in seen:
            continue
        seen.add(key)
        role = _normalize_role(str(row.get("role", "MID")))
        bonus_goal = int(row.get("bonus_goal", 0) or 0)
        bonus_cs = int(row.get("bonus_clean_sheet", 0) or 0)
        if role != "GK":
            bonus_cs = 0
        players.append(
            PlayerBonus(
                name=name,
                side=side,
                role=role,
                bonus_goal=bonus_goal,
                bonus_clean_sheet=bonus_cs,
                vice_allenatore=bool(row.get("vice", False)),
            )
        )

    if len(players) < 4:
        raise ValueError(
            f"Vision: letti solo {len(players)} giocatori (servono almeno 4 oltre al vice)"
        )

    _validate_roster_sides(players)
    _ensure_single_vice(players)

    return MatchRoster(
        match_id=_default_match_id(home, away),
        home=home,
        away=away,
        players=players,
    )


def _call_openai_vision(images: list[bytes]) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY non impostata")

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Extract the full FM roster from these {len(images)} screenshot(s). "
                "JSON only."
            ),
        }
    ]
    for blob in images[:_MAX_IMAGES]:
        encoded = base64.standard_b64encode(blob).decode("ascii")
        mime = _guess_mime(blob)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}", "detail": "high"},
            }
        )

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = 90.0  # vision multi-immagine: non usare http_timeout (FM_FAST_MODE=10s)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI vision HTTP {exc.code}: {detail[:300]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"OpenAI vision timeout/rete dopo {timeout:.0f}s: {exc}"
        ) from exc

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI vision: risposta vuota")
    message = choices[0].get("message") or {}
    raw = message.get("content") or ""
    if not raw.strip():
        raise RuntimeError("OpenAI vision: JSON vuoto")
    return _extract_json(raw)


def roster_from_vision(images: list[bytes]) -> MatchRoster:
    """Parse FM screenshots via OpenAI vision (gpt-4o-mini)."""
    if not images:
        raise ValueError("Nessuno screenshot per vision")
    if len(images) > _MAX_IMAGES:
        raise ValueError(f"Massimo {_MAX_IMAGES} screenshot per analisi")
    data = _call_openai_vision(images)
    return roster_from_vision_data(data)
