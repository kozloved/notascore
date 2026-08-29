#!/usr/bin/env bash
# Start the YourMT3 / mt3-infer HTTP worker. Bind 0.0.0.0 so Vast.ai / RunPod can reach it.
set -euo pipefail
cd "$(dirname "$0")"
export MT3_MODEL="${MT3_MODEL:-yourmt3}"
export MT3_WARMUP="${MT3_WARMUP:-1}"
PORT="${PORT:-8090}"
echo "Starting MT3 worker on 0.0.0.0:${PORT} model=${MT3_MODEL} warmup=${MT3_WARMUP}"
exec python -m uvicorn mt3_gpu_worker:app --host 0.0.0.0 --port "$PORT"
