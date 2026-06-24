#!/usr/bin/env bash
# Launch MathSnip. Creates a local virtualenv on first run.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (first run)…"
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
fi

# Always sync deps (fast once satisfied). Prevents a half-installed venv from
# silently running without an OCR engine. Not quiet, so a big first-time
# download (PyTorch, ONNX Runtime, etc.) shows progress instead of looking hung.
echo "Checking dependencies (first run downloads ~1-2 GB of ML libraries)…"
./.venv/bin/pip install -r requirements.txt

exec ./.venv/bin/python -m mathsnip
