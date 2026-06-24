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
# Prefer requirements.lock (the exact, known-good versions captured from a
# working machine). If it can't install here — e.g. a different architecture
# where a pinned wheel doesn't exist — fall back to the bounded requirements.txt.
echo "Installing dependencies (first run downloads ~1-2 GB of ML libraries)…"
if [ -f requirements.lock ] && ./.venv/bin/pip install -r requirements.lock; then
  echo "Installed exact versions from requirements.lock."
else
  echo "Using requirements.txt (no usable lock for this machine)."
  ./.venv/bin/pip install -r requirements.txt
fi

exec ./.venv/bin/python -m mathsnip
