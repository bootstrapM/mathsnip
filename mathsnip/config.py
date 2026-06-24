"""Configuration loading/saving.

Config lives at ~/.mathsnip/config.json. On first run an *annotated* default
file is written (it supports `//` comments so you can remember what each option
does). Comments are stripped before parsing, so the file stays valid for the app
while remaining human-friendly.

Secrets (API keys) can also be supplied via an environment variable so you don't
have to store them on disk:

    MATHSNIP_CLOUD_API_KEY   overrides cloud.api_key
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

CONFIG_DIR = Path.home() / ".mathsnip"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Canonical defaults (also the fallback if a key is missing from the user file).
DEFAULT_CONFIG: Dict[str, Any] = {
    "engine": "local",
    "pix2text_mode": "formula",
    "device": None,
    "hotkey": "<cmd>+<ctrl>+m",
    "default_copy_format": "latex_inline",
    "show_window": True,
    "history_size": None,
    "preprocess": False,
    "cloud": {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key": "",
        "mathpix_app_id": "",
        "mathpix_app_key": "",
    },
}

# Human-friendly annotated template written on first run. Keep values in sync
# with DEFAULT_CONFIG above.
ANNOTATED_DEFAULT = """\
{
  // ===== MathSnip configuration =====
  // After editing, restart the app for changes to take effect.
  // "//" comments are allowed here; they're ignored when the file is read.

  // Which OCR path to use:
  //   "local" = the on-device Pix2Text model (offline, free, private)
  //   "cloud" = the cloud API (needs a key under "cloud" below)
  "engine": "local",

  // On-device model: Pix2Text (mfr-1.5). Mode:
  //   "formula"      = treat the snip as a single equation (fast, scored)
  //   "text_formula" = mixed text + math; returns Markdown with embedded LaTeX
  //                    (slower, downloads more models, more Mathpix-like)
  "pix2text_mode": "formula",

  // Compute device for the local model:
  //   null   = pick automatically
  //   "cpu"  = force CPU
  //   "gpu" / "cuda" = use GPU if available
  "device": null,

  // Global capture hotkey (pynput syntax). Examples:
  //   "<cmd>+<ctrl>+m"  (default, like Mathpix)
  //   "<cmd>+<shift>+2"
  "hotkey": "<cmd>+<ctrl>+m",

  // Which format is auto-copied to the clipboard after each snip. One of:
  //   "latex_inline"   ->  $ ... $
  //   "latex_display"  ->  \\\\[ ... \\\\]
  //   "latex_raw"      ->  exactly what the model returned
  //   "markdown"       ->  $$ ... $$
  //   "mathml"         ->  MathML (good for pasting into Word)
  "default_copy_format": "latex_inline",

  // Show the result panel after each snip. If false, MathSnip just copies the
  // chosen format silently and shows a small notification.
  "show_window": true,

  // How many recent snips to keep in the panel's history (and on disk at
  // ~/.mathsnip/history.json). null = keep all; or set a number to cap it.
  "history_size": null,

  // Pre-scale/pad the image before local OCR. Usually leave OFF: Pix2Text
  // resizes internally, and extra preprocessing tends to hurt.
  "preprocess": false,

  // Cloud engine settings (only used when engine is "cloud").
  // Leave as-is if you only use the local model.
  "cloud": {
    // "openai" = any OpenAI-compatible vision API (OpenAI, Gemini via an
    //            OpenAI-compatible endpoint, OpenRouter, local Ollama, etc.)
    // "mathpix" = the real Mathpix API (uses the app_id/app_key below)
    "provider": "openai",

    // Base URL of the OpenAI-compatible endpoint.
    "base_url": "https://api.openai.com/v1",

    // Vision-capable model name at that endpoint.
    "model": "gpt-4o-mini",

    // API key. You can leave this empty and instead set the environment
    // variable MATHSNIP_CLOUD_API_KEY so the key never sits in this file.
    "api_key": "",

    // Only for provider == "mathpix":
    "mathpix_app_id": "",
    "mathpix_app_key": ""
  }
}
"""


def _strip_jsonc(text: str) -> str:
    """Remove // line comments and /* */ block comments, ignoring those that
    appear inside double-quoted strings (so URLs like https://... survive)."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:      # keep escaped char verbatim
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def write_annotated_default() -> None:
    """(Re)write the annotated default config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(ANNOTATED_DEFAULT)


def load_config() -> Dict[str, Any]:
    """Load config, writing the annotated default on first run, applying env
    overrides, and filling in any keys missing from an older file."""
    if not CONFIG_PATH.exists():
        write_annotated_default()

    try:
        raw = CONFIG_PATH.read_text()
        user = json.loads(_strip_jsonc(raw)) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        user = {}

    cfg = _deep_merge(DEFAULT_CONFIG, user)

    env_key = os.environ.get("MATHSNIP_CLOUD_API_KEY")
    if env_key:
        cfg["cloud"]["api_key"] = env_key
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """Write a plain (non-annotated) JSON config. Used when the app updates
    settings programmatically; comments are not preserved."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
