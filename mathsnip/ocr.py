"""Hybrid OCR engine: the local Pix2Text model first, cloud vision API fallback.

The local engine is breezedeus/Pix2Text (lazy-loaded; weights download on first
use). It uses the SOTA `mfr-1.5` formula model via its `LatexOCR` class, which
also returns a real confidence score. In "text_formula" mode it uses the full
pipeline to handle mixed text + math, returning Markdown.

The engine is chosen by config: "local" (Pix2Text) or "cloud" (OpenAI-compatible
vision API). The local model also returns a confidence score, shown in the panel.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

_CLOUD_PROMPT = (
    "You are an OCR engine that transcribes the math and text in an image into "
    "LaTeX. Output ONLY the LaTeX for what is shown, with no explanation, no "
    "surrounding $ delimiters, and no markdown code fences. Preserve inline "
    "text as plain words and math as LaTeX."
)


@dataclass
class OcrResult:
    latex: str
    source: str                       # "local", "cloud", "local(fallback-failed)"
    error: Optional[str] = None
    score: Optional[float] = None      # local confidence in [0,1] when available


# A local engine returns (text, score) where score is None if the model
# doesn't provide one.
ScoredText = Tuple[str, Optional[float]]


def _maybe_preprocess(image_path: str, preprocess: bool) -> str:
    if not preprocess:
        return image_path
    try:
        from .preprocess import preprocess_image
        return preprocess_image(image_path)
    except Exception:
        return image_path


class Pix2TextEngine:
    """breezedeus/Pix2Text. Default local engine.

    mode == "formula":      pure-equation recognition via the mfr-1.5 model
                            (fast ONNX, returns a confidence score).
    mode == "text_formula": full pipeline for mixed text+math, returns Markdown
                            (no single score).
    """

    name = "pix2text"

    def __init__(self, mode: str = "formula", preprocess: bool = False,
                 device: Optional[str] = None) -> None:
        self.mode = mode if mode in ("formula", "text_formula") else "formula"
        self.preprocess = preprocess
        self.device = device
        self._formula = None   # LatexOCR (mfr)
        self._full = None      # Pix2Text pipeline
        self.import_error = None   # set if pix2text exists but fails to import

    def available(self) -> bool:
        try:
            import pix2text  # noqa: F401
            return True
        except ModuleNotFoundError as exc:
            # pix2text itself missing -> genuinely not installed.
            if (exc.name or "").split(".")[0] == "pix2text":
                self.import_error = None
            else:
                self.import_error = exc   # a dependency is missing/broken
            return False
        except Exception as exc:  # noqa: BLE001
            # Installed but failed to import (e.g. NumPy/torch ABI mismatch).
            self.import_error = exc
            return False

    def _ensure(self) -> None:
        if self.mode == "formula":
            if self._formula is None:
                from pix2text import LatexOCR
                self._formula = LatexOCR(device=self.device)
        else:
            if self._full is None:
                from pix2text import Pix2Text
                self._full = Pix2Text.from_config(device=self.device)

    def warm_up(self) -> None:
        self._ensure()

    def predict_scored(self, image_path: str) -> ScoredText:
        self._ensure()
        path = _maybe_preprocess(image_path, self.preprocess)
        if self.mode == "formula":
            out = self._formula.recognize(path)  # {"text":..., "score":...}
            if isinstance(out, dict):
                return out.get("text", ""), out.get("score")
            return str(out), None
        # text_formula: returns Markdown with embedded LaTeX, no single score.
        md = self._full.recognize_text_formula(path, return_text=True)
        return (md if isinstance(md, str) else str(md)), None


def build_local_engine(config: Dict[str, Any]) -> "Pix2TextEngine":
    """Build the local Pix2Text engine from config."""
    # GPU/CUDA isn't supported here (macOS has no CUDA; Pix2Text maps gpu->cuda).
    # Ignore any stale "gpu"/"cuda" device so it can't crash model load — let
    # the runtime auto-pick (CoreML/CPU).
    device = config.get("device")
    if isinstance(device, str) and device.lower() in ("gpu", "cuda"):
        device = None
    return Pix2TextEngine(
        mode=config.get("pix2text_mode", "formula"),
        preprocess=config.get("preprocess", False),
        device=device,  # None -> auto
    )


class CloudEngine:
    """OpenAI-compatible vision call, or the Mathpix API, depending on config."""

    def __init__(self, cloud_cfg: Dict[str, Any]) -> None:
        self.cfg = cloud_cfg or {}

    def configured(self) -> bool:
        provider = self.cfg.get("provider", "openai")
        if provider == "mathpix":
            return bool(self.cfg.get("mathpix_app_id") and self.cfg.get("mathpix_app_key"))
        return bool(self.cfg.get("api_key"))

    def predict(self, image_path: str) -> str:
        provider = self.cfg.get("provider", "openai")
        if provider == "mathpix":
            return self._predict_mathpix(image_path)
        return self._predict_openai(image_path)

    @staticmethod
    def _b64(image_path: str) -> str:
        with open(image_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")

    def _predict_openai(self, image_path: str) -> str:
        import requests
        b64 = self._b64(image_path)
        url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        payload = {
            "model": self.cfg.get("model", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": _CLOUD_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this to LaTeX."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                },
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.cfg.get('api_key', '')}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    def _predict_mathpix(self, image_path: str) -> str:
        import requests
        b64 = self._b64(image_path)
        resp = requests.post(
            "https://api.mathpix.com/v3/text",
            json={
                "src": f"data:image/png;base64,{b64}",
                "formats": ["latex_styled"],
                "ocr": ["math", "text"],
            },
            headers={
                "app_id": self.cfg.get("mathpix_app_id", ""),
                "app_key": self.cfg.get("mathpix_app_key", ""),
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("latex_styled") or data.get("text") or "").strip()


class OcrEngine:
    """Routes a capture to either the local or the cloud engine per config."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.local = build_local_engine(config)
        self.cloud = CloudEngine(config.get("cloud", {}))

    def recognize(self, image_path: str) -> OcrResult:
        if self.config.get("engine", "local") == "cloud":
            return self._cloud_only(image_path)
        return self._local_only(image_path)

    def _local_unavailable_msg(self) -> str:
        err = getattr(self.local, "import_error", None)
        if err is not None:
            return (f"Pix2Text failed to load: {err}. "
                    "Usually a torch version mismatch — this stack needs "
                    "torch 2.4.x (pip install 'torch>=2.4,<2.5').")
        return "Pix2Text is not installed (pip install pix2text)."

    def _local_only(self, image_path: str) -> OcrResult:
        if not self.local.available():
            return OcrResult("", "local", error=self._local_unavailable_msg())
        try:
            text, score = self.local.predict_scored(image_path)
            return OcrResult(text, "local", score=score)
        except Exception as exc:  # noqa: BLE001
            return OcrResult("", "local", error=f"Local OCR failed: {exc}")

    def _cloud_only(self, image_path: str) -> OcrResult:
        if not self.cloud.configured():
            return OcrResult("", "cloud", error="Cloud engine is not configured.")
        try:
            return OcrResult(self.cloud.predict(image_path), "cloud")
        except Exception as exc:  # noqa: BLE001
            return OcrResult("", "cloud", error=f"Cloud OCR failed: {exc}")


# Backwards-compatible alias.
HybridOCR = OcrEngine
