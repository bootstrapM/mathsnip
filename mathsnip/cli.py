"""Headless CLI: OCR an image file and print the formats. No GUI required.

    python -m mathsnip.cli path/to/equation.png
    python -m mathsnip.cli path/to/equation.png --format mathml
"""
from __future__ import annotations

import argparse
import sys

from .config import load_config
from .convert import build_formats
from .ocr import HybridOCR


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OCR an image to LaTeX.")
    parser.add_argument("image", help="Path to an image file.")
    parser.add_argument(
        "--format",
        choices=["latex_raw", "latex_inline", "latex_display", "markdown", "mathml", "all"],
        default="all",
        help="Which format to print (default: all).",
    )
    args = parser.parse_args(argv)

    config = load_config()
    engine = HybridOCR(config)
    result = engine.recognize(args.image)

    if result.error and not result.latex:
        print(f"error: {result.error}", file=sys.stderr)
        return 1

    formats = build_formats(result.latex).as_dict()
    print(f"# source: {result.source}", file=sys.stderr)
    if args.format == "all":
        for key, val in formats.items():
            print(f"--- {key} ---")
            print(val)
    else:
        print(formats[args.format])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
