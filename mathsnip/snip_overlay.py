"""Custom full-screen snip overlay (Mathpix-style).

When a capture starts we grab a screenshot of the screen under the cursor, then
show a frameless full-screen widget that:
  * dims the whole screen (grayed out),
  * draws full-span horizontal + vertical crosshair lines through the cursor,
  * reveals the original (un-dimmed) pixels inside the drag selection,
  * on release, crops the selection from the screenshot and returns its path.

Esc (or a zero-size selection) cancels. Closing the overlay restores the screen
since we only ever drew an overlay on top — the real screen is untouched.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class SnipOverlay(QWidget):
    def __init__(self, on_done: Callable[[Optional[str]], None]) -> None:
        super().__init__()
        self._on_done = on_done
        self._done = False

        screen = (QGuiApplication.screenAt(self._cursor())
                  or QGuiApplication.primaryScreen())
        self._screen = screen
        self._shot = screen.grabWindow(0)          # full screenshot (device px)
        self._dpr = self._shot.devicePixelRatio() or 1.0

        self._origin: Optional[QPoint] = None
        self._cur = self.mapFromGlobal(self._cursor())
        self._selecting = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Plain show() at the screen's geometry — avoids the macOS native
        # full-screen "Space" animation that makes showFullScreen() feel janky.
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.grabKeyboard()

    @staticmethod
    def _cursor() -> QPoint:
        from PyQt6.QtGui import QCursor
        return QCursor.pos()

    # -- events -------------------------------------------------------------
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._origin = e.pos()
            self._cur = e.pos()
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        self._cur = e.pos()
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or not self._selecting:
            return
        self._selecting = False
        rect = QRect(self._origin, e.pos()).normalized()
        if rect.width() < 4 or rect.height() < 4:
            self._finish(None)          # treat a tiny selection as a cancel
            return
        self._finish(self._save_crop(rect))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self._finish(None)

    # -- painting -----------------------------------------------------------
    def paintEvent(self, _evt) -> None:  # noqa: N802
        p = QPainter(self)
        full = self.rect()
        # Base screenshot, then a bluish-white veil matching the panel theme.
        p.drawPixmap(full, self._shot)
        p.fillRect(full, QColor(237, 243, 252, 175))

        if self._selecting and self._origin is not None:
            sel = QRect(self._origin, self._cur).normalized()
            # Reveal original (un-dimmed) pixels inside the selection.
            src = QRect(int(sel.x() * self._dpr), int(sel.y() * self._dpr),
                        int(sel.width() * self._dpr), int(sel.height() * self._dpr))
            p.drawPixmap(sel, self._shot, src)
            p.setPen(QPen(QColor("#2f6fd0"), 2))   # theme-blue selection border
            p.drawRect(sel)
            # Size readout (dark, for the light veil).
            p.setPen(QColor("#244"))
            p.drawText(sel.x(), max(14, sel.y() - 6),
                       f"{sel.width()} × {sel.height()}")

        # Full-span crosshair through the cursor (dark bluish, for the light veil).
        pen = QPen(QColor(70, 100, 150, 200), 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(0, self._cur.y(), full.width(), self._cur.y())
        p.drawLine(self._cur.x(), 0, self._cur.x(), full.height())
        p.end()

    # -- finish -------------------------------------------------------------
    def _save_crop(self, rect: QRect) -> Optional[str]:
        try:
            src = QRect(int(rect.x() * self._dpr), int(rect.y() * self._dpr),
                        int(rect.width() * self._dpr), int(rect.height() * self._dpr))
            cropped = self._shot.copy(src)
            cropped.setDevicePixelRatio(1.0)
            out = Path(tempfile.gettempdir()) / f"mathsnip_{int(time.time()*1000)}.png"
            return str(out) if cropped.save(str(out), "PNG") else None
        except Exception:  # noqa: BLE001
            return None

    def _finish(self, path: Optional[str]) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.releaseKeyboard()
        except Exception:  # noqa: BLE001
            pass
        self.close()
        self._on_done(path)
