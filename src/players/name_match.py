"""Player name normalization and fuzzy matching."""

from __future__ import annotations

import re
import unicodedata


def normalize_player(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = text.split()
    if len(parts) >= 2 and len(parts[-1]) == 1:
        parts = parts[:-1]
    return " ".join(parts)


def players_match(fm_name: str, api_name: str) -> bool:
    fm = normalize_player(fm_name)
    api = normalize_player(api_name)
    if not fm or not api:
        return False
    if fm == api:
        return True
    fm_tokens = fm.split()
    api_tokens = api.split()
    if fm_tokens[-1] == api_tokens[-1]:
        return True
    # FM "Rodriguez R." vs API "R. Rodriguez"
    if len(fm_tokens) == 1 and api_tokens and fm_tokens[0] == api_tokens[-1]:
        return True
    if fm in api or api in fm:
        return True
    return False
