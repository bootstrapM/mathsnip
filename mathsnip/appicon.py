"""Shared app-icon drawing: crop-corner brackets framing an italic 'fx'
('snip the math'). Used both for the menu-bar icon (white) and the About
dialog (dark), so they stay identical."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap


def app_icon_pixmap(size: int = 44, color: str = "#1a1a1a") -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    ink = QColor(color)

    # Crop-corner brackets.
    m = int(size * 0.12)
    L = int(size * 0.26)
    pen = QPen(ink, max(2, int(size * 0.07)))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    lo, hi = m, size - m
    p.drawLine(lo, lo, lo + L, lo); p.drawLine(lo, lo, lo, lo + L)
    p.drawLine(hi, lo, hi - L, lo); p.drawLine(hi, lo, hi, lo + L)
    p.drawLine(lo, hi, lo + L, hi); p.drawLine(lo, hi, lo, hi - L)
    p.drawLine(hi, hi, hi - L, hi); p.drawLine(hi, hi, hi, hi - L)

    # Italic f(x) in the middle.
    p.setPen(ink)
    font = QFont("Georgia")
    font.setPixelSize(int(size * 0.42))
    font.setBold(True)
    font.setItalic(True)
    p.setFont(font)
    p.drawText(pix.rect(), int(Qt.AlignmentFlag.AlignCenter), "fx")
    p.end()
    return pix


def app_icon(size: int = 44, color: str = "#ffffff") -> QIcon:
    return QIcon(app_icon_pixmap(size, color))
