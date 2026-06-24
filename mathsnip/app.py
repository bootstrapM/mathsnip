"""MathSnip menu-bar application.

A single PyQt6 event loop drives everything:
  * QSystemTrayIcon  -> the menu-bar presence (the "Snip" menu)
  * pynput listener  -> global hotkey, on a background thread
  * QThread worker   -> runs capture + OCR off the UI thread
  * ResultWindow     -> the formatted output panel

Run with:  python -m mathsnip
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QFont
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .appicon import app_icon
from .capture import capture_from_clipboard, capture_region
from .clipboard import copy_text
from .config import CONFIG_PATH, load_config, save_config, write_annotated_default
from .convert import build_formats
from .ocr import HybridOCR, OcrResult
from .result_window import ResultWindow
from .snip_overlay import SnipOverlay


def _make_icon() -> QIcon:
    """Menu-bar icon: white crop-corner brackets framing an italic 'fx'."""
    return app_icon(44, "#ffffff")


class OcrWorker(QObject):
    """Runs one capture+OCR job on a worker thread."""
    finished = pyqtSignal(object)  # emits OcrResult or None (cancelled)

    def __init__(self, engine: HybridOCR, image_path: str) -> None:
        super().__init__()
        self.engine = engine
        self.image_path = image_path

    def run(self) -> None:
        try:
            result = self.engine.recognize(self.image_path)
        except Exception as exc:  # noqa: BLE001
            result = OcrResult("", "local", error=str(exc))
        self.finished.emit(result)


class MathSnipApp(QObject):
    # Signal so the pynput thread can ask the UI thread to start a capture.
    trigger_capture = pyqtSignal(str)  # "region" | "clipboard"

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.config = load_config()
        self.engine = HybridOCR(self.config)
        self._panel = None        # single reusable result panel
        self._overlay = None      # active snip overlay (keep ref while open)
        self._threads = []        # keep refs to running threads
        self._workers = []        # keep refs so workers aren't GC'd mid-run
        self._hotkey_listener = None

        self._build_tray()
        self.trigger_capture.connect(self._on_capture)
        self._start_hotkey()
        self._warm_up_model()

        try:
            from .result_window import _HAS_WEBENGINE
            print(f"[mathsnip] rendered preview available: {_HAS_WEBENGINE}",
                  file=sys.stderr, flush=True)
        except Exception:
            pass

    def _warm_up_model(self) -> None:
        """Load the local model in the background at launch so the first snip
        isn't stuck waiting on a cold model load."""
        if self.config.get("engine") == "cloud":
            return
        import threading

        def _load() -> None:
            try:
                local = self.engine.local
                if local.available() and hasattr(local, "_ensure"):
                    local._ensure()
                    print(f"[mathsnip] local model warmed up ({local.name})",
                          file=sys.stderr, flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[mathsnip] warm-up failed: {exc}", file=sys.stderr, flush=True)

        threading.Thread(target=_load, daemon=True).start()

    # -- tray ---------------------------------------------------------------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(_make_icon(), self.app)
        self.tray.setToolTip("MathSnip — click to open")
        # No context menu: clicking the icon opens the panel directly (the menu
        # actions live behind the ⚙ gear inside the panel). A small fallback
        # menu is kept on right-click so Quit is always reachable.
        self.tray.activated.connect(self._on_tray_activated)

        fallback = QMenu()
        fallback.addAction("Show Window", self._show_panel)
        fallback.addAction("Snip & Convert", lambda: self._on_capture("region"))
        fallback.addSeparator()
        fallback.addAction("Quit MathSnip", self.app.quit)
        self._tray_fallback = fallback
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        Reason = QSystemTrayIcon.ActivationReason
        if reason in (Reason.Context,):
            # Right-click: show the tiny fallback menu (Quit safety net).
            self._tray_fallback.popup(self._cursor_global())
        else:
            # Left-click toggles the panel: open if hidden, hide if showing.
            if self._panel is not None and self._panel.isVisible():
                self._panel.hide()
            else:
                self._show_panel()

    @staticmethod
    def _cursor_global():
        from PyQt6.QtGui import QCursor
        return QCursor.pos()

    def _open_config(self) -> None:
        import subprocess
        subprocess.run(["open", str(CONFIG_PATH)], check=False)

    def _open_settings(self) -> None:
        """Open the GUI settings editor; on Save, persist to disk.

        We deliberately do NOT hot-swap the OCR engine or restart the global
        hotkey listener — re-initialising those native components (torch/onnx,
        the macOS event tap) at runtime can crash the process. Changes apply on
        the next launch."""
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.config, parent=self._panel)
        if not dlg.exec():          # Rejected / closed
            return
        try:
            new_cfg = dlg.result_config()
            changed = new_cfg != self.config   # compare before env-key blanking
            # Don't persist an env-injected API key to disk.
            env_key = os.environ.get("MATHSNIP_CLOUD_API_KEY")
            if env_key and new_cfg.get("cloud", {}).get("api_key") == env_key:
                new_cfg["cloud"]["api_key"] = ""
            save_config(new_cfg)
            self.config = load_config()
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Couldn't save settings: {exc}")
            return

        if not changed:
            self.tray.showMessage("MathSnip", "No changes.",
                                  QSystemTrayIcon.MessageIcon.Information, 1500)
            return

        box = QMessageBox(self._panel)
        box.setWindowTitle("MathSnip")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Settings saved.")
        box.setInformativeText("Restart MathSnip now to apply the changes?")
        restart_btn = box.addButton("Restart now",
                                    QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is restart_btn:
            self._restart()

    def _restart(self) -> None:
        """Launch a fresh independent instance, then quit this one.

        We spawn a new process rather than os.execv-ing in place: re-execing a
        macOS menu-bar (Cocoa) app in the same process can't cleanly re-establish
        the status-bar item, so the app would run with no visible icon."""
        import subprocess
        # Release the global hotkey first so the new instance can grab it.
        try:
            if self._hotkey_listener is not None:
                self._hotkey_listener.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            subprocess.Popen([sys.executable, "-m", "mathsnip"],
                             cwd=os.getcwd(), start_new_session=True)
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Couldn't restart automatically: {exc}")
            return
        # Give the child a moment to start, then quit this instance.
        QTimer.singleShot(400, self.app.quit)

    def _reset_config(self) -> None:
        """Back up any existing config and write a fresh annotated default."""
        import subprocess
        try:
            if CONFIG_PATH.exists():
                backup = CONFIG_PATH.with_suffix(".json.bak")
                CONFIG_PATH.replace(backup)
            write_annotated_default()
            self.tray.showMessage(
                "MathSnip",
                "Config reset to annotated default (old one saved as "
                "config.json.bak). Restart to apply.",
                QSystemTrayIcon.MessageIcon.Information, 4000)
            subprocess.run(["open", str(CONFIG_PATH)], check=False)
        except Exception as exc:  # noqa: BLE001
            self._notify(f"Couldn't reset config: {exc}")

    # -- hotkey -------------------------------------------------------------
    def _start_hotkey(self) -> None:
        hotkey = self.config.get("hotkey")
        if not hotkey:
            return
        try:
            from pynput import keyboard
        except Exception:
            return

        def on_activate() -> None:
            # Called on pynput's thread; hop to the UI thread via the signal.
            self.trigger_capture.emit("region")

        try:
            self._hotkey_listener = keyboard.GlobalHotKeys({hotkey: on_activate})
            self._hotkey_listener.start()
        except Exception:
            self._hotkey_listener = None

    # -- capture + OCR flow -------------------------------------------------
    def _on_capture(self, mode: str) -> None:
        print(f"[mathsnip] capture triggered (mode={mode})", file=sys.stderr, flush=True)
        if mode == "clipboard":
            image_path = capture_from_clipboard()
            if not image_path:
                self._notify("No image found on the clipboard.")
                return
            self._start_ocr(image_path)
            return

        # Region: hide our own panel so it isn't part of the screenshot. The
        # hide is processed asynchronously by the window server, so wait a beat
        # before grabbing the screen, otherwise the panel shows up in the snip.
        if self._panel is not None and self._panel.isVisible():
            self._panel.hide()
            QApplication.processEvents()
            QTimer.singleShot(180, self._begin_region_snip)
        else:
            self._begin_region_snip()

    def _begin_region_snip(self) -> None:
        try:
            self._overlay = SnipOverlay(self._on_region_done)
        except Exception as exc:  # noqa: BLE001
            print(f"[mathsnip] overlay failed, falling back to screencapture: {exc}",
                  file=sys.stderr, flush=True)
            path = capture_region()
            if path:
                self._start_ocr(path)

    def _on_region_done(self, image_path: Optional[str]) -> None:
        print(f"[mathsnip] region snip -> {image_path}", file=sys.stderr, flush=True)
        if not image_path:
            return  # cancelled
        self._start_ocr(image_path)

    def _start_ocr(self, image_path: str) -> None:
        print("[mathsnip] starting OCR…", file=sys.stderr, flush=True)
        self.tray.showMessage("MathSnip", "Recognizing…",
                              QSystemTrayIcon.MessageIcon.Information, 1500)
        # Run OCR off the UI thread. Keep refs to BOTH the thread and the worker
        # so neither is garbage-collected before the job finishes.
        thread = QThread()
        worker = OcrWorker(self.engine, image_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ocr_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._threads.append(thread)
        self._workers.append(worker)

        def _cleanup() -> None:
            if thread in self._threads:
                self._threads.remove(thread)
            if worker in self._workers:
                self._workers.remove(worker)

        thread.finished.connect(_cleanup)
        thread.start()

    def _on_ocr_done(self, result: OcrResult) -> None:
        if result is None:
            return
        print(f"[mathsnip] OCR done: source={result.source} "
              f"score={result.score} latex_len={len(result.latex or '')} "
              f"error={result.error}", file=sys.stderr, flush=True)
        formats = build_formats(result.latex)

        # Auto-copy the configured default format (via pbcopy for reliability).
        key = self.config.get("default_copy_format", "latex_inline")
        to_copy = formats.as_dict().get(key, formats.latex_inline)
        copied = copy_text(to_copy) if to_copy else False
        print(f"[mathsnip] clipboard copy ({key}) -> {copied}",
              file=sys.stderr, flush=True)

        if result.error and not result.latex:
            self._notify(result.error)

        if self.config.get("show_window", True):
            print("[mathsnip] updating result panel", file=sys.stderr, flush=True)
            self._ensure_panel()
            self._panel.set_anchor(self.tray.geometry())
            self._panel.set_result(formats, result.source, result.error, result.score)
            self._panel.show_anchored()
        elif copied:
            self.tray.showMessage("MathSnip", "Copied to clipboard.",
                                  QSystemTrayIcon.MessageIcon.Information, 2000)

    def _ensure_panel(self) -> ResultWindow:
        if self._panel is None:
            self._panel = ResultWindow(
                history_size=self.config.get("history_size"),
                callbacks={
                    "snip": lambda: self._on_capture("region"),
                    "clipboard": lambda: self._on_capture("clipboard"),
                    "open_settings": self._open_settings,
                    "open_config": self._open_config,
                    "reset_config": self._reset_config,
                    "quit": self.app.quit,
                },
            )
        return self._panel

    def _show_panel(self) -> None:
        """Re-open the result panel (with history) without taking a new snip."""
        panel = self._ensure_panel()
        panel.set_anchor(self.tray.geometry())
        panel.show_anchored()

    def _notify(self, text: str) -> None:
        self.tray.showMessage("MathSnip", text,
                              QSystemTrayIcon.MessageIcon.Warning, 4000)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MathSnip")
    app.setQuitOnLastWindowClosed(False)  # menu-bar app: stay alive with no window

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "MathSnip", "No system tray available.")
        return 1

    _ = MathSnipApp(app)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
