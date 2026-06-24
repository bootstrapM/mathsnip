"""Convert a raw LaTeX string into the various output formats MathSnip offers.

Mirrors the Mathpix result panel: inline LaTeX, display/equation LaTeX,
Markdown, and MathML (which Word and many editors can import).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict


@dataclass
class Formats:
    latex_raw: str        # exactly what the OCR returned
    latex_inline: str     # $ ... $
    latex_display: str    # \[ ... \]  (display equation)
    latex_equation: str   # \begin{equation} ... \end{equation}
    markdown: str         # $$ ... $$ block, ready to paste into Markdown
    mathml: str           # MathML <math> ... </math>

    def as_dict(self) -> Dict[str, str]:
        return {
            "latex_raw": self.latex_raw,
            "latex_inline": self.latex_inline,
            "latex_display": self.latex_display,
            "latex_equation": self.latex_equation,
            "markdown": self.markdown,
            "mathml": self.mathml,
        }


def _clean(latex: str) -> str:
    """Trim whitespace and strip any wrapping math delimiters the model added."""
    s = (latex or "").strip()
    # Remove a single layer of surrounding delimiters if present.
    for left, right in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if s.startswith(left) and s.endswith(right) and len(s) >= len(left) + len(right):
            s = s[len(left):len(s) - len(right)].strip()
            break
    return s


def to_mathml(latex: str) -> str:
    """Best-effort LaTeX -> MathML. Always returns *well-formed* MathML or ''.

    latex2mathml can emit invalid XML for some inputs (e.g. the alignment tab
    in \\begin{aligned} becomes a bare, unescaped '&'). We strip those
    artifacts, escape any stray ampersands, and validate the result so the app
    never hands Word/other tools broken XML."""
    import re
    import xml.dom.minidom as _minidom

    core = _clean(latex)
    if not core:
        return ""
    try:
        from latex2mathml.converter import convert as _l2mml
    except Exception:
        return ""
    try:
        mml = _l2mml(core)
    except Exception:
        return ""
    if not mml:
        return ""

    # Drop alignment-tab artifacts ('<mi>&</mi>') and escape any stray '&'
    # that isn't already part of a valid XML entity (&...; or &#...;).
    mml = mml.replace("<mi>&</mi>", "")
    mml = re.sub(r"&(?!#?[0-9A-Za-z]+;)", "&amp;", mml)

    try:
        _minidom.parseString(mml)   # final well-formedness guarantee
    except Exception:
        return ""
    return mml


def build_formats(latex: str) -> Formats:
    core = _clean(latex)
    return Formats(
        latex_raw=latex.strip() if latex else "",
        latex_inline=f"${core}$" if core else "",
        latex_display=f"\\[\n{core}\n\\]" if core else "",
        latex_equation=f"\\begin{{equation}}\n{core}\n\\end{{equation}}" if core else "",
        markdown=f"$$\n{core}\n$$" if core else "",
        mathml=to_mathml(core),
    )


# Heuristic to flag a low-quality local result (used only when no confidence
# score is available, e.g. text_formula mode).
_REPEAT_RE = re.compile(r"(.{2,8})\1{4,}")  # same short chunk repeated >=5x


def looks_low_confidence(latex: str) -> bool:
    """Crude quality check on a LaTeX string.

    Used as a fallback only when the engine gives no confidence score (e.g.
    text_formula mode): we flag results that are empty, suspiciously short, or
    contain obvious degenerate repetition (a common out-of-distribution failure).
    """
    s = _clean(latex)
    if len(s) < 2:
        return True
    if _REPEAT_RE.search(s):
        return True
    # Unbalanced braces are a strong signal of a broken parse.
    if s.count("{") and abs(s.count("{") - s.count("}")) > 2:
        return True
    return False
