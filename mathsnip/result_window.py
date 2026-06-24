"""The result panel: a single, reusable, frameless dropdown anchored to the
top-right of the screen, styled after Mathpix Snip.

Layout (top to bottom):
  * toolbar: Snip · Clipboard | ‹  i/N  › ............ ⚙ (settings)
  * preview: the rendered equation (auto-resizes the panel to fit)
  * format rows: LaTeX / Inline / Display / Equation / Markdown / MathML + Copy
  * confidence bar (green = high, red = low)

History is navigated with the ‹ › arrows and persisted to disk.
"""
from __future__ import annotations

import html as _html
import math
import time
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, QLineF, QPointF, QRectF, QSize, QTimer, QUrl
from PyQt6.QtGui import (
    QColor, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .clipboard import copy_text
from .convert import Formats, build_formats
from .history import load_history, make_entry, save_history

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except Exception:  # noqa: BLE001
    _HAS_WEBENGINE = False

# (config key, row label) for the format rows shown under the preview.
# Lean set: raw LaTeX, inline, and MathML (the only non-LaTeX format).
_FORMAT_ROWS = [
    ("latex_raw", "LaTeX"),
    ("latex_inline", "Inline  $…$"),
    ("mathml", "MathML"),
]


# Icons are rendered at this internal resolution (floats, antialiased) and let
# Qt scale them down to the button's icon size — crisp and perfectly symmetric.
_ICON_RES = 96


def _trash_icon(color: str = "#333") -> QIcon:
    """High-contrast trash-bin icon (the trash glyph renders as a faint outline
    that looks like a disabled button)."""
    S = _ICON_RES
    pm = QPixmap(S, S)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), S * 0.07)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    lid = S * 0.30
    p.drawLine(QLineF(S * 0.18, lid, S * 0.82, lid))                 # lid
    p.drawLine(QLineF(S * 0.40, S * 0.16, S * 0.60, S * 0.16))       # handle top
    p.drawLine(QLineF(S * 0.40, S * 0.16, S * 0.40, lid))
    p.drawLine(QLineF(S * 0.60, S * 0.16, S * 0.60, lid))
    p.drawLine(QLineF(S * 0.26, lid, S * 0.32, S * 0.84))            # body sides
    p.drawLine(QLineF(S * 0.74, lid, S * 0.68, S * 0.84))
    p.drawLine(QLineF(S * 0.32, S * 0.84, S * 0.68, S * 0.84))       # body base
    for fx in (0.42, 0.50, 0.58):                                    # ribs
        p.drawLine(QLineF(S * fx, lid + S * 0.06, S * fx, S * 0.76))
    p.end()
    return QIcon(pm)


def _gear_icon(color: str = "#333") -> QIcon:
    """Settings gear (the ⚙ glyph is missing/skewed in many fonts).
    Concentric ring + hole with eight evenly-spaced teeth."""
    S = _ICON_RES
    pm = QPixmap(S, S)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), S * 0.085)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    c = S / 2.0
    r = S * 0.27           # ring radius
    tooth = S * 0.12       # tooth length beyond the ring
    for k in range(8):
        a = math.radians(k * 45.0)
        ca, sa = math.cos(a), math.sin(a)
        p.drawLine(QLineF(c + ca * r, c + sa * r,
                          c + ca * (r + tooth), c + sa * (r + tooth)))
    p.drawEllipse(QPointF(c, c), r, r)            # outer ring (concentric)
    p.drawEllipse(QPointF(c, c), S * 0.10, S * 0.10)  # inner hole (concentric)
    p.end()
    return QIcon(pm)


def _preview_html(core: str) -> str:
    """MathJax page rendering `core` as display math. Config uses doubled
    backslashes (JS escaping); the body uses single backslashes so MathJax's
    DOM scan finds real \\[ ... \\] delimiters."""
    safe = _html.escape(core, quote=False)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        "<script>"
        "window.MathJax={tex:{displayMath:[['\\\\[','\\\\]']],"
        "inlineMath:[['$','$'],['\\\\(','\\\\)']]},svg:{fontCache:'global'},"
        "startup:{typeset:true}};"
        "</script>"
        '<script id="MathJax-script" async '
        'src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>'
        "<style>html,body{margin:0;padding:18px;display:flex;"
        "align-items:center;justify-content:center;"
        "font-family:-apple-system,system-ui,sans-serif;color:#111;"
        "background:#fff;}#eq{font-size:24px;line-height:1.5;}</style>"
        "</head><body><div id=\"eq\">\\[" + safe + "\\]</div></body></html>"
    )


class ConfidenceBar(QWidget):
    """Full-width bar: width ∝ score, hue red→green, value at the end."""

    def __init__(self) -> None:
        super().__init__()
        self._score: Optional[float] = None
        self.setFixedHeight(16)

    def set_score(self, score: Optional[float]) -> None:
        self._score = score
        self.setVisible(score is not None)
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        if self._score is None:
            return
        s = max(0.0, min(1.0, float(self._score)))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_w, bar_h = 44, 9
        bar_w = max(20, self.width() - text_w)
        y = (self.height() - bar_h) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e3e3e3"))
        p.drawRoundedRect(0, y, bar_w, bar_h, 4, 4)
        if s > 0:
            p.setBrush(QColor.fromHsv(int(120 * s), 200, 205))
            p.drawRoundedRect(0, y, max(6, int(bar_w * s)), bar_h, 4, 4)
        p.setPen(QColor("#444"))
        p.drawText(bar_w + 6, 0, text_w - 6, self.height(),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   f"{s:.0%}")
        p.end()


class _FormatRow(QWidget):
    """A read-only, horizontally-scrollable field for one format + Copy button.

    Long LaTeX/MathML strings overflow the row; the inner scroll area shows a
    horizontal scrollbar so the whole string can be viewed by scrolling, while
    the Copy button always copies the full (original) text."""

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(34)   # fixed row height so rows never stretch
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        self._text = ""

        self.scroll = QScrollArea()
        self.scroll.setFixedHeight(30)
        self.scroll.setWidgetResizable(False)   # let the label size to content
        # No visible scrollbar (it ate space in a short row); the content still
        # scrolls horizontally via a two-finger trackpad swipe / shift+wheel.
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea{background:#ffffff;border:1px solid #c2d2e8;"
            "border-radius:5px;}")
        self.scroll.viewport().setStyleSheet("background:#ffffff;")
        self.label = QLabel()
        self.label.setWordWrap(False)
        self.label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setStyleSheet("color:#111;background:transparent;padding:6px;")
        self.scroll.setWidget(self.label)
        lay.addWidget(self.scroll, 1)

        btn = QPushButton("Copy")
        btn.setFixedWidth(58)
        btn.clicked.connect(lambda: copy_text(self._text))
        lay.addWidget(btn)

    def set_text(self, text: str) -> None:
        self._text = text or ""
        self.label.setText(self._text.replace("\n", " ") or "(no output)")
        self.label.adjustSize()   # update width so the scrollbar appears


def _tool_button(text: str, tip: str, on_click: Callable) -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setFixedHeight(26)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(lambda: on_click())
    return b


class ResultWindow(QWidget):
    def __init__(self, history_size=None,
                 callbacks: Optional[Dict[str, Callable]] = None) -> None:
        super().__init__()
        self.setWindowTitle("MathSnip")
        self.resize(560, 460)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Transparent window so the rounded container's corners show through.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.cb = callbacks or {}
        # None / non-positive => keep ALL history; a positive int caps it.
        self._history_cap = (history_size if isinstance(history_size, int)
                             and history_size > 0 else None)
        self._history: List[Dict[str, Any]] = load_history()
        if self._history_cap:
            self._history = self._history[: self._history_cap]
        self._index = 0
        # Auto-resize bookkeeping. _resize_next: a measure is pending after the
        # next preview load. _resize_anchor: True = re-anchor to top-right (new
        # snip); False = keep top-left fixed so the toolbar/arrows don't move.
        self._resize_next = False
        self._resize_anchor = True
        self._anchor_rect = None   # the tray icon's screen rect, set by the app

        # Outer layout holds a single rounded container; the window itself is
        # transparent, so only the container (with rounded corners) is visible.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setObjectName("panel")
        # Bluish-white, lightly translucent so the desktop subtly shows through.
        # We force a light scheme for all children so text/icons stay dark and
        # readable regardless of the system (dark-mode) palette.
        container.setStyleSheet(
            "#panel{background:rgba(237,243,252,0.9);"
            "border:1px solid rgba(176,196,224,0.9);border-radius:14px;}"
            "#panel QLabel{color:#1a1a1a;background:transparent;}"
            "#panel QPushButton{color:#1a1a1a;background:rgba(255,255,255,0.7);"
            "border:1px solid rgba(170,190,220,0.85);border-radius:6px;"
            "padding:2px 7px;}"
            "#panel QPushButton:hover{background:rgba(255,255,255,0.95);}"
            "#panel QPushButton:disabled{color:#9aa6b5;"
            "background:rgba(255,255,255,0.35);}"
            "#panel QMenu{background:#f4f7fc;color:#1a1a1a;"
            "border:1px solid #b0c4e0;}"
            "#panel QMenu::item:selected{background:#d6e2f5;}")
        outer.addWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)
        root.addLayout(self._build_toolbar())

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#6b7686;font-size:11px;")
        root.addWidget(self.status)

        root.addWidget(self._build_preview(), 1)
        root.addWidget(self._build_format_rows())

        conf_row = QHBoxLayout()
        lbl = QLabel("Confidence")
        lbl.setStyleSheet("color:#888;font-size:11px;")
        conf_row.addWidget(lbl)
        self.conf_bar = ConfidenceBar()
        conf_row.addWidget(self.conf_bar, 1)
        root.addLayout(conf_row)

        if self._history:
            self._show_index(0)
        else:
            self._update_counter()

    # -- toolbar ------------------------------------------------------------
    def _build_toolbar(self) -> QHBoxLayout:
        ink = "#2a2a2a"   # fixed dark for the light panel (don't follow dark mode)
        bar = QHBoxLayout()
        bar.setSpacing(6)

        # Three zones. The left and right zones get EQUAL stretch, so they are
        # always equal width -> the center nav cluster sits at the true window
        # center (not merely centered between the side tools).
        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(_tool_button("⛶  Snip", "New snip (capture screen)",
                                  self.cb.get("snip", lambda: None)))
        ll.addStretch(1)

        center = QWidget()
        cc = QHBoxLayout(center)
        cc.setContentsMargins(0, 0, 0, 0)
        cc.setSpacing(6)
        self.btn_oldest = _tool_button("«", "Oldest snip", self._go_oldest)
        self.btn_oldest.setFixedWidth(30)
        cc.addWidget(self.btn_oldest)
        self.btn_prev = _tool_button("‹", "Older snip", self._go_older)
        self.btn_prev.setFixedWidth(30)
        cc.addWidget(self.btn_prev)
        self.counter = QLabel("0/0")
        self.counter.setStyleSheet("color:#555;min-width:46px;")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cc.addWidget(self.counter)
        self.btn_next = _tool_button("›", "Newer snip", self._go_newer)
        self.btn_next.setFixedWidth(30)
        cc.addWidget(self.btn_next)
        self.btn_newest = _tool_button("»", "Newest snip", self._go_newest)
        self.btn_newest.setFixedWidth(30)
        cc.addWidget(self.btn_newest)

        right = QWidget()
        rr = QHBoxLayout(right)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(6)
        rr.addStretch(1)
        self.btn_del = QPushButton()
        self.btn_del.setIcon(_trash_icon(ink))
        self.btn_del.setIconSize(QSize(18, 18))
        self.btn_del.setToolTip("Delete this snip from history")
        self.btn_del.setFixedSize(34, 26)
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.clicked.connect(self._delete_current)
        rr.addWidget(self.btn_del)

        gear = QPushButton()
        gear.setIcon(_gear_icon(ink))
        gear.setIconSize(QSize(20, 20))
        gear.setToolTip("Settings")
        gear.setFixedSize(38, 26)
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setStyleSheet("QPushButton{padding:0px;}"
                           "QPushButton::menu-indicator{image:none;width:0px;}")
        menu = QMenu(gear)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet(
            "QMenu{background:#f4f7fc;color:#1a1a1a;border:1px solid #b0c4e0;"
            "border-radius:10px;padding:5px;}"
            "QMenu::item{padding:5px 16px;border-radius:6px;}"
            "QMenu::item:selected{background:#d6e2f5;}"
            "QMenu::separator{height:1px;background:#cdd9ec;margin:4px 8px;}")
        menu.addAction("Snip & Convert", self.cb.get("snip", lambda: None))
        menu.addSeparator()
        menu.addAction("Settings…", self.cb.get("open_settings", lambda: None))
        menu.addAction("Open Config File…", self.cb.get("open_config", lambda: None))
        menu.addAction("Reset Config to Annotated Default…",
                       self.cb.get("reset_config", lambda: None))
        menu.addSeparator()
        menu.addAction("About MathSnip", self._show_about)
        menu.addAction("Hide Window", self.hide)
        menu.addAction("Quit MathSnip", self.cb.get("quit", lambda: None))
        gear.setMenu(menu)
        rr.addWidget(gear)

        bar.addWidget(left, 1)     # equal-width side zones keep...
        bar.addWidget(center, 0)   # ...the center nav cluster at the
        bar.addWidget(right, 1)    # true window center
        return bar

    def _show_about(self) -> None:
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        from .appicon import app_icon_pixmap
        try:
            from . import __version__ as ver
        except Exception:  # noqa: BLE001
            ver = "0.1.0"

        dlg = QDialog(self)
        dlg.setWindowTitle("About MathSnip")
        dlg.setStyleSheet("QDialog{background:#eef3fb;} QLabel{background:transparent;}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(30, 22, 30, 18)
        lay.setSpacing(4)
        center = Qt.AlignmentFlag.AlignCenter

        icon = QLabel()
        icon.setPixmap(app_icon_pixmap(72, "#2a4060"))
        icon.setAlignment(center)
        lay.addWidget(icon)

        name = QLabel("MathSnip")
        name.setAlignment(center)
        name.setStyleSheet("font-size:19px;font-weight:500;color:#1a1a1a;")
        lay.addWidget(name)

        version = QLabel(f"version {ver}")
        version.setAlignment(center)
        version.setStyleSheet("font-size:11px;color:#8893a5;")
        lay.addWidget(version)

        lay.addSpacing(10)

        desc = QLabel(
            "An open-source, self-hosted alternative to Mathpix Snip for macOS. "
            "Snip an equation on screen and get clean LaTeX, a rendered preview, "
            "and MathML.")
        desc.setWordWrap(True)
        desc.setAlignment(center)
        desc.setStyleSheet("font-size:11px;font-weight:300;color:#3a4452;")
        lay.addWidget(desc)

        lay.addSpacing(8)

        engine = QLabel(
            "Engine: on-device <b>Pix2Text</b> (mfr-1.5) formula-recognition "
            "model — runs fully offline, with an optional cloud fallback.")
        engine.setTextFormat(Qt.TextFormat.RichText)
        engine.setWordWrap(True)
        engine.setAlignment(center)
        engine.setStyleSheet("font-size:11px;font-weight:300;color:#3a4452;")
        lay.addWidget(engine)

        lay.addSpacing(10)

        credit = QLabel(
            "Created by Himanshu Raj, in collaboration with Claude."
            "<br>MIT License")
        credit.setTextFormat(Qt.TextFormat.RichText)
        credit.setWordWrap(True)
        credit.setAlignment(center)
        credit.setStyleSheet("font-size:11px;font-weight:300;color:#6b7686;")
        lay.addWidget(credit)

        lay.addSpacing(12)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        lay.addWidget(buttons)
        dlg.setFixedWidth(380)
        dlg.exec()

    def _build_preview(self) -> QWidget:
        if _HAS_WEBENGINE:
            self._web = QWebEngineView()
            self._web.setMinimumHeight(110)
            self._web.loadFinished.connect(self._on_preview_loaded)
            return self._web
        self._web = None
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        note = QLabel("Rendered preview needs PyQt6-WebEngine.\n"
                      "Install:  pip install PyQt6-WebEngine")
        note.setStyleSheet("color:#888;")
        note.setWordWrap(True)
        lay.addWidget(note)
        self._preview_fallback = QPlainTextEdit()
        self._preview_fallback.setReadOnly(True)
        lay.addWidget(self._preview_fallback)
        return wrap

    def _build_format_rows(self) -> QWidget:
        # Fixed-height stack of rows inside a rounded box that's a touch darker
        # bluish-white than the panel, so the copy region reads as one frame.
        box = QFrame()
        box.setObjectName("fmtbox")
        box.setStyleSheet(
            "#fmtbox{background:rgba(221,231,246,0.95);"
            "border:1px solid rgba(168,189,221,0.9);border-radius:10px;}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)
        self._rows: Dict[str, _FormatRow] = {}
        for key, _label in _FORMAT_ROWS:
            row = _FormatRow()
            self._rows[key] = row
            lay.addWidget(row)
        return box

    # -- history nav --------------------------------------------------------
    def _go_older(self) -> None:
        if self._index < len(self._history) - 1:
            self._show_index(self._index + 1)

    def _go_newer(self) -> None:
        if self._index > 0:
            self._show_index(self._index - 1)

    def _go_oldest(self) -> None:
        if self._history:
            self._show_index(len(self._history) - 1)

    def _go_newest(self) -> None:
        if self._history:
            self._show_index(0)

    def _show_index(self, i: int) -> None:
        if not self._history:
            return
        self._index = max(0, min(i, len(self._history) - 1))
        entry = self._history[self._index]
        wh = entry.get("wh")
        if wh:
            # Seen before: resize instantly from the cached size (no wait),
            # keeping the top-left fixed so the arrows stay put.
            self._resize_next = False
            self._display(entry)
            self._apply_size(wh[0], wh[1], anchor=False)
        else:
            # First view: measure after the preview renders, then cache it.
            self._resize_next = True
            self._resize_anchor = False
            self._display(entry)
        self._update_counter()

    def _delete_current(self) -> None:
        if not self._history:
            return
        del self._history[self._index]
        save_history(self._history)
        if not self._history:
            self._index = 0
            self._clear_display()
        else:
            self._index = min(self._index, len(self._history) - 1)
            self._display(self._history[self._index])
        self._update_counter()

    def _clear_display(self) -> None:
        self.conf_bar.set_score(None)
        self.status.setText("")
        for row in self._rows.values():
            row.set_text("")
        if self._web is not None:
            self._web.setHtml("<html><body></body></html>")
        elif hasattr(self, "_preview_fallback"):
            self._preview_fallback.setPlainText("")

    def _update_counter(self) -> None:
        total = len(self._history)
        pos = (self._index + 1) if total else 0
        self.counter.setText(f"{pos}/{total}")
        older = self._index < total - 1
        newer = self._index > 0
        self.btn_prev.setEnabled(older)
        self.btn_oldest.setEnabled(older)
        self.btn_next.setEnabled(newer)
        self.btn_newest.setEnabled(newer)
        self.btn_del.setEnabled(total > 0)

    # -- display ------------------------------------------------------------
    def set_result(self, formats: Formats, source: str,
                   error: Optional[str] = None,
                   score: Optional[float] = None) -> None:
        entry = make_entry(formats.latex_raw, source, score)
        self._history.insert(0, entry)
        if self._history_cap:
            del self._history[self._history_cap:]
        save_history(self._history)
        self._index = 0
        self._resize_next = True    # measure + resize after this snip renders
        self._resize_anchor = True  # a fresh snip re-anchors to the top-right
        self._display(entry, error)
        self._update_counter()

    @staticmethod
    def _status_text(source: str, error: Optional[str]) -> str:
        labels = {"local": "Recognized locally",
                  "cloud": "Recognized via cloud"}
        base = labels.get(source, source or "")
        return f"{base} — {error}" if error else base

    def _display(self, entry: Dict[str, Any], error: Optional[str] = None) -> None:
        formats = build_formats(entry.get("latex", ""))
        score = entry.get("score")
        self.conf_bar.set_score(score if isinstance(score, (int, float)) else None)

        self.status.setText(self._status_text(entry.get("source", ""), error))
        self.status.setStyleSheet(
            "color:#b00020;font-size:11px;" if error
            else "color:#6b7686;font-size:11px;")

        data = formats.as_dict()
        for key, row in self._rows.items():
            row.set_text(data.get(key, ""))

        core = (formats.latex_inline or "").strip("$")
        if self._web is not None:
            self._web.setHtml(
                _preview_html(core) if core else "<html><body></body></html>",
                QUrl("https://cdn.jsdelivr.net/"),
            )
        elif hasattr(self, "_preview_fallback"):
            self._preview_fallback.setPlainText(formats.latex_inline)

    # -- auto-resize --------------------------------------------------------
    def _on_preview_loaded(self, _ok) -> None:
        if self._resize_next:
            self._resize_next = False
            QTimer.singleShot(300, self._resize_to_equation)

    def _resize_to_equation(self) -> None:
        if self._web is None:
            return
        js = ("(function(){var e=document.getElementById('eq');"
              "if(!e)return [0,0];var r=e.getBoundingClientRect();"
              "return [Math.ceil(r.width),Math.ceil(r.height)];})()")
        try:
            self._web.page().runJavaScript(js, self._apply_equation_size)
        except Exception:  # noqa: BLE001
            pass

    def _apply_equation_size(self, res) -> None:
        try:
            w, h = int(res[0]), int(res[1])
        except Exception:  # noqa: BLE001
            return
        if w <= 0 or h <= 0:
            return
        # Cache the measured size on the current entry for instant re-display.
        if self._history and 0 <= self._index < len(self._history):
            self._history[self._index]["wh"] = [w, h]
        self._apply_size(w, h, self._resize_anchor)

    def _apply_size(self, w_eq: int, h_eq: int, anchor: bool) -> None:
        if self._web is None:
            return
        screen = QGuiApplication.screenAt(self._cursor_pos()) \
            or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        max_w = int(geo.width() * 0.9)
        new_w = max(480, min(w_eq + 90, max_w))
        prev_h = max(110, min(h_eq + 56, 380))

        center_x = self.x() + self.width() / 2   # remember the horizontal center
        top = self.y()
        # The preview is the flexible (stretch) element; the copy rows + conf
        # bar are fixed and pinned to the bottom, so no gap can open below the
        # rows. We just size the window so the preview ends up ~prev_h tall.
        old_ph = self._web.height()
        if old_ph > 0:
            new_h = self.height() - old_ph + prev_h
        else:
            new_h = 34 + prev_h + len(self._rows) * 38 + 28 + 40  # rough first time
        new_h = max(220, new_h)
        self.resize(new_w, new_h)
        if anchor:
            self._reanchor()
        else:
            # Keep the horizontal CENTER fixed: both margins flex symmetrically,
            # so the centered nav arrows stay in place (like Mathpix).
            new_x = int(center_x - self.width() / 2)
            new_x = max(geo.left() + 8, min(new_x, geo.right() - self.width() - 8))
            self.move(new_x, top)

    # -- window -------------------------------------------------------------
    def show_anchored(self) -> None:
        self._reanchor()
        self.show()
        self.raise_()
        self.activateWindow()

    def set_anchor(self, rect) -> None:
        """Tell the panel where the menu-bar icon is, so it can drop below it."""
        self._anchor_rect = rect

    def _reanchor(self) -> None:
        a = self._anchor_rect
        use_icon = a is not None and a.width() > 0 and a.height() > 0
        screen = (QGuiApplication.screenAt(a.center()) if use_icon
                  else QGuiApplication.screenAt(self._cursor_pos())) \
            or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        if use_icon:
            # Drop the panel straight down from the icon, horizontally centered
            # under it (like Mathpix), just below the menu bar.
            x = a.center().x() - self.width() // 2
            y = a.bottom() + 6
        else:
            x = geo.right() - self.width() - 12
            y = geo.top() + 12
        x = max(geo.left() + 8, min(x, geo.right() - self.width() - 8))
        y = max(geo.top() + 4, y)
        self.move(x, y)

    @staticmethod
    def _cursor_pos():
        from PyQt6.QtGui import QCursor
        return QCursor.pos()
