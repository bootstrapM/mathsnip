#!/usr/bin/env bash
# Launch MathSnip. Creates a local virtualenv on first run.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (first run)…"
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
fi

# Install dependencies (first run downloads ~1-2 GB of ML libraries).
# requirements.txt uses bounded pins (numpy<2, optimum<2, opencv-python<4.12)
# that resolve to a consistent set on both Intel and Apple Silicon.
echo "Installing dependencies (first run downloads ~1-2 GB of ML libraries)…"
./.venv/bin/pip install -r requirements.txt

exec ./.venv/bin/python -m mathsnip
