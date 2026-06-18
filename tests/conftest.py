"""Pytest defaults — keep unit tests offline and deterministic."""

import os

os.environ.setdefault("FM_LINEUP_WEB_SEARCH", "0")
