"""Persistent snip history stored at ~/.mathsnip/history.json.

Each entry records what's needed to re-display a past result; the various
formats are re-derived from the raw LaTeX on demand.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from .config import CONFIG_DIR

HISTORY_PATH = CONFIG_DIR / "history.json"


def load_history() -> List[Dict[str, Any]]:
    try:
        data = json.loads(HISTORY_PATH.read_text())
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_history(entries: List[Dict[str, Any]]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(entries, indent=2))
    except OSError:
        pass


def make_entry(latex: str, source: str, score: Any) -> Dict[str, Any]:
    return {
        "ts": time.time(),
        "latex": latex or "",
        "source": source,
        "score": score,
    }
