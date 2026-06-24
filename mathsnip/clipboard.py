"""Reliable clipboard writing on macOS.

Qt's QClipboard can be flaky from a menu-bar app with no focused window, so we
write via the native `pbcopy` first and fall back to Qt only if that fails.
"""
from __future__ import annotations

import subprocess


def copy_text(text: str) -> bool:
    if not text:
        return False
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        pass
    try:
        from PyQt6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
            return True
    except Exception:
        pass
    return False
