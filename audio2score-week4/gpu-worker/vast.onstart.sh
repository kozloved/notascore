#!/usr/bin/env bash
# Vast.ai onstart: boot the YourMT3 GPU worker on port 8090.
# Paste this as the instance OnStart script, or run it over SSH.
set -euo pipefail

WORKER_DIR="${WORKER_DIR:-/workspace/notascore-gpu}"
PORT="${PORT:-8090}"
export MT3_MODEL="${MT3_MODEL:-yourmt3}"
export MT3_WARMUP="${MT3_WARMUP:-1}"
export MT3_CHECKPOINT_DIR="${MT3_CHECKPOINT_DIR:-/workspace/mt3-checkpoints}"

mkdir -p "$WORKER_DIR" "$MT3_CHECKPOINT_DIR"
cd "$WORKER_DIR"

if [[ ! -f mt3_gpu_worker.py ]]; then
  echo "gpu-worker files missing in $WORKER_DIR"
  echo "Either copy audio2score-week4/gpu-worker/* here, or clone the repo:"
  echo "  git clone https://github.com/kozloved/notascore.git /workspace/notascore"
  echo "  cp /workspace/notascore/audio2score-week4/gpu-worker/* $WORKER_DIR/"
  exit 1
fi

python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

python -m pip install -U pip
python -m pip install -r requirements.txt

echo "Pre-downloading ${MT3_MODEL} checkpoint into ${MT3_CHECKPOINT_DIR} ..."
python - <<'PY'
import os
from mt3_infer import download_model
name = os.getenv("MT3_MODEL", "yourmt3")
print("download", name, download_model(name))
PY

chmod +x start.sh
exec ./start.sh
