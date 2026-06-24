"""Screen-region capture for macOS.

Uses the built-in `screencapture -i` which gives the exact native crosshair /
drag-to-select experience Mathpix Snip uses. Returns the path to a PNG, or
None if the user pressed Esc to cancel.
"""
from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional


def capture_region() -> Optional[str]:
    """Interactively select a screen region; return PNG path or None if cancelled.

    `screencapture -i` writes a file only if the user completes a selection;
    on Esc it writes nothing and exits 0, so we detect cancellation by checking
    whether the file was actually created and is non-empty.
    """
    tmp = Path(tempfile.gettempdir()) / f"mathsnip_{int(time.time()*1000)}.png"
    # -i interactive, -s force mouse-selection (no window mode), -x no sound.
    try:
        subprocess.run(
            ["screencapture", "-i", "-s", "-x", str(tmp)],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    if tmp.exists() and tmp.stat().st_size > 0:
        return str(tmp)
    return None


def capture_from_clipboard() -> Optional[str]:
    """Save the current clipboard image to a PNG and return its path, else None.

    Lets you OCR an image you've already copied (Cmd+Shift+Ctrl+4, screenshots,
    etc.) without re-snipping.
    """
    try:
        from PIL import ImageGrab
    except Exception:
        return None
    img = ImageGrab.grabclipboard()
    if img is None or isinstance(img, list):
        return None
    tmp = Path(tempfile.gettempdir()) / f"mathsnip_clip_{int(time.time()*1000)}.png"
    try:
        img.save(tmp, "PNG")
    except Exception:
        return None
    return str(tmp)
