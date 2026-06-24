"""Image preprocessing to (optionally) improve local OCR quality.

Formula models are resolution- and margin-sensitive: they're trained on rendered LaTeX
with a white background and some padding, at glyph sizes larger than a tight,
low-DPI screen snip usually provides. This pass nudges captures toward that
distribution:

  * flatten any transparency onto a white background
  * upscale small images so character height is in a comfortable range
  * gently normalise contrast (rescues faint / anti-aliased text)
  * add a white margin (the model expects breathing room around the formula)

It is deliberately conservative — no binarisation or denoising, which tend to
destroy thin strokes (fraction bars, primes, dots) and hurt more than help.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Optional

# Target minimum content height in pixels before padding is added.
_TARGET_MIN_HEIGHT = 120
# Never upscale more than this, to avoid blowing up large captures.
_MAX_SCALE = 5.0


def preprocess_image(path: str) -> str:
    """Return a path to a preprocessed PNG, or the original path on any failure."""
    try:
        from PIL import Image, ImageOps
    except Exception:
        return path

    try:
        img = Image.open(path)

        # 1) Flatten transparency onto white.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(bg, img).convert("RGB")
        else:
            img = img.convert("RGB")

        # 2) Upscale small captures so glyphs are large enough to read.
        w, h = img.size
        if h > 0 and h < _TARGET_MIN_HEIGHT:
            scale = min(_TARGET_MIN_HEIGHT / h, _MAX_SCALE)
            if scale > 1.01:
                img = img.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.LANCZOS,
                )

        # 3) Gentle contrast normalisation (ignore the 1% extreme pixels).
        img = ImageOps.autocontrast(img, cutoff=1)

        # 4) Add a white margin proportional to the image size.
        pad = max(12, int(0.06 * min(img.size)))
        img = ImageOps.expand(img, border=pad, fill=(255, 255, 255))

        out = Path(tempfile.gettempdir()) / f"mathsnip_pre_{int(time.time()*1000)}.png"
        img.save(out, "PNG")
        return str(out)
    except Exception:
        # Any issue: fall back to the untouched original.
        return path
