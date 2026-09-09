#!/usr/bin/env bash
# Clone PM2S, install CPU torch in the backend venv, and fetch Zenodo weights.
# Does not change production defaults. After this, set in backend/.env:
#   TRANSCRIPTION_HAND_SEPARATOR=pm2s
#   TRANSCRIPTION_QUANTIZATION_MODE=pm2s
#   TRANSCRIPTION_PM2S_REQUIRED=1
#   PM2S_REPO=<repo>/vendor/pm2s
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BACKEND_DIR/../.." && pwd)"
PM2S_REPO="${PM2S_REPO:-$REPO_ROOT/vendor/pm2s}"
VENV="${VENV:-$BACKEND_DIR/.venv}"
PYTHON="${VENV}/bin/python"
PIP="${VENV}/bin/pip"

if [ ! -x "$PYTHON" ]; then
  echo "No venv at $VENV. Create audio2score-week4/backend/.venv first." >&2
  exit 1
fi

mkdir -p "$(dirname "$PM2S_REPO")"
if [ ! -d "$PM2S_REPO/.git" ]; then
  git clone --depth 1 https://github.com/cheriell/PM2S.git "$PM2S_REPO"
else
  echo "PM2S already cloned at $PM2S_REPO"
fi

"$PIP" install torch --index-url https://download.pytorch.org/whl/cpu
"$PIP" install pandas

WEIGHT_ROOT="$PM2S_REPO/pm2s/_model_state_dicts"
mkdir -p "$WEIGHT_ROOT/beat" "$WEIGHT_ROOT/quantisation" "$WEIGHT_ROOT/hand_part"

download() {
  local url="$1" dest="$2"
  if [ -s "$dest" ]; then
    echo "already have $dest"
    return
  fi
  echo "downloading $url"
  curl -L --fail --retry 3 --retry-delay 2 -o "$dest" "$url"
}

download "https://zenodo.org/records/10520196/files/RNNJointBeatModel.pth?download=1" \
  "$WEIGHT_ROOT/beat/RNNJointBeatModel.pth"
download "https://zenodo.org/records/10520196/files/RNNJointQuantisationModel.pth?download=1" \
  "$WEIGHT_ROOT/quantisation/RNNJointQuantisationModel.pth"
download "https://zenodo.org/records/10520196/files/RNNHandPartModel.pth?download=1" \
  "$WEIGHT_ROOT/hand_part/RNNHandPartModel.pth"

cd "$BACKEND_DIR"
export PM2S_REPO
"$PYTHON" - <<'PY'
import os
import sys

sys.path.insert(0, ".")
from mir.pm2s_hands import pm2s_status

print(pm2s_status())
PY

cat <<EOF

PM2S is ready at $PM2S_REPO

Add to audio2score-week4/backend/.env (testing only; production stays viterbi/off):

TRANSCRIPTION_HAND_SEPARATOR=pm2s
TRANSCRIPTION_QUANTIZATION_MODE=pm2s
TRANSCRIPTION_PM2S_REQUIRED=1
PM2S_REPO=$PM2S_REPO

Smoke:  cd audio2score-week4/backend && .venv/bin/python scripts/pm2s_smoke.py
Live tests: .venv/bin/python -m pytest tests/test_pm2s_live.py -m pm2s -q
EOF
