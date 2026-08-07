#!/usr/bin/env bash
# Idempotent dependency bootstrap for the NotaScore / Audio2Score app.
# Safe to run repeatedly: it (re)creates the backend virtualenv and installs
# Python + Node dependencies, then seeds local .env files if missing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/audio2score-week4"

# basic-pitch / tensorflow require Python < 3.12, so prefer python3.11.
PYTHON_BIN="$(command -v python3.11 || command -v python3)"
echo "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

echo "==> Backend dependencies"
cd "$APP_DIR/backend"
if [ ! -x .venv/bin/python ]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt
[ -f .env ] || cp .env.example .env

echo "==> Frontend dependencies"
cd "$APP_DIR/frontend"
npm install
[ -f .env.local ] || cp .env.local.example .env.local

echo "==> install.sh complete"
