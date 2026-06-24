"""A GUI settings editor, so users don't have to hand-edit config.json.

Builds form controls from the current config and returns an updated config dict
(it does not save or apply — the app does that so it can also reload the engine
and hotkey).
"""
from __future__ import annotations

import copy
from typing import Any, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_COPY_FORMATS = ["latex_inline", "latex_raw", "latex_display",
                 "latex_equation", "markdown", "mathml"]


def _combo(items, current) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    if current in items:
        c.setCurrentText(current)
    return c


class SettingsDialog(QDialog):
    def __init__(self, config: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MathSnip Settings")
        self.setMinimumWidth(440)
        self._cfg = copy.deepcopy(config)
        cloud = self._cfg.get("cloud", {})

        root = QVBoxLayout(self)

        # --- Engine / recognition ---------------------------------------
        eng_box = QGroupBox("Recognition")
        eng = QFormLayout(eng_box)
        self.engine = _combo(["local", "cloud"],
                             self._cfg.get("engine", "local"))
        self.engine.setToolTip("local = on-device Pix2Text (offline). "
                               "cloud = OpenAI-compatible API.")
        eng.addRow("Engine", self.engine)

        self.mode = _combo(["formula", "text_formula"],
                           self._cfg.get("pix2text_mode", "formula"))
        self.mode.setToolTip("formula = single equation (fast). "
                            "text_formula = mixed text+math, returns Markdown.")
        eng.addRow("Pix2Text mode", self.mode)

        # Pix2Text mode only matters for the local engine -> hide it for cloud.
        def _toggle_mode() -> None:
            eng.setRowVisible(self.mode, self.engine.currentText() == "local")
        self.engine.currentTextChanged.connect(lambda *_: _toggle_mode())
        _toggle_mode()
        root.addWidget(eng_box)

        # --- Behaviour ---------------------------------------------------
        beh_box = QGroupBox("Behaviour")
        beh = QFormLayout(beh_box)
        self.hotkey = QLineEdit(self._cfg.get("hotkey", "<cmd>+<ctrl>+m"))
        self.hotkey.setToolTip("pynput syntax, e.g. <cmd>+<ctrl>+m")
        beh.addRow("Capture hotkey", self.hotkey)

        self.copy_fmt = _combo(_COPY_FORMATS,
                              self._cfg.get("default_copy_format", "latex_inline"))
        beh.addRow("Auto-copy format", self.copy_fmt)

        self.show_window = QCheckBox("Show the result panel after each snip")
        self.show_window.setChecked(bool(self._cfg.get("show_window", True)))
        beh.addRow("", self.show_window)

        self.preprocess = QCheckBox("Pre-scale/pad image before local OCR")
        self.preprocess.setChecked(bool(self._cfg.get("preprocess", False)))
        beh.addRow("", self.preprocess)

        self.keep_all = QCheckBox("Keep all history")
        self.hist = QSpinBox()
        self.hist.setRange(1, 100000)
        hs = self._cfg.get("history_size")
        if isinstance(hs, int) and hs > 0:
            self.keep_all.setChecked(False)
            self.hist.setValue(hs)
        else:
            self.keep_all.setChecked(True)
            self.hist.setValue(50)
        self.hist.setEnabled(not self.keep_all.isChecked())
        self.keep_all.toggled.connect(lambda on: self.hist.setEnabled(not on))
        hist_row = QWidget()
        hr = QFormLayout(hist_row)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.addRow(self.keep_all)
        hr.addRow("History size (if not all)", self.hist)
        beh.addRow("History", hist_row)
        root.addWidget(beh_box)

        # --- Cloud -------------------------------------------------------
        cloud_box = QGroupBox("Cloud engine — OpenAI-compatible "
                              "(used when Engine is 'cloud')")
        cl = QFormLayout(cloud_box)
        self.base_url = QLineEdit(cloud.get("base_url", ""))
        cl.addRow("Base URL", self.base_url)
        self.model = QLineEdit(cloud.get("model", ""))
        cl.addRow("Model", self.model)
        self.api_key = QLineEdit(cloud.get("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("blank = use MATHSNIP_CLOUD_API_KEY env var")
        cl.addRow("API key", self.api_key)
        root.addWidget(cloud_box)

        note = QLabel("Saved settings take effect on the next launch "
                      "(restart MathSnip to apply).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;font-size:11px;")
        root.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def result_config(self) -> Dict[str, Any]:
        """Build the updated config dict from the current widget values."""
        cfg = copy.deepcopy(self._cfg)
        cfg["engine"] = self.engine.currentText()
        cfg["pix2text_mode"] = self.mode.currentText()
        cfg["hotkey"] = self.hotkey.text().strip() or "<cmd>+<ctrl>+m"
        cfg["default_copy_format"] = self.copy_fmt.currentText()
        cfg["show_window"] = self.show_window.isChecked()
        cfg["preprocess"] = self.preprocess.isChecked()
        cfg["history_size"] = None if self.keep_all.isChecked() else self.hist.value()
        cfg.setdefault("cloud", {})
        cfg["cloud"]["provider"] = "openai"
        cfg["cloud"]["base_url"] = self.base_url.text().strip()
        cfg["cloud"]["model"] = self.model.text().strip()
        cfg["cloud"]["api_key"] = self.api_key.text()
        return cfg
