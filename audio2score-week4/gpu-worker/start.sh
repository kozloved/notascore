#!/usr/bin/env bash
# GPU worker entrypoint.
# RunPod Serverless sets RUNPOD_ENDPOINT_ID and must run handler.py.
# Vast.ai / GPU pods use the FastAPI HTTP server on PORT (default 8090).
set -euo pipefail
cd "$(dirname "$0")"
export MT3_MODEL="${MT3_MODEL:-yourmt3}"
export MT3_WARMUP="${MT3_WARMUP:-1}"
PORT="${PORT:-8090}"

if [[ -n "${RUNPOD_ENDPOINT_ID:-}" || "${MT3_SERVERLESS:-}" == "1" ]]; then
  echo "Starting MT3 RunPod Serverless handler model=${MT3_MODEL}"
  exec python -u handler.py
fi

echo "Starting MT3 HTTP worker on 0.0.0.0:${PORT} model=${MT3_MODEL} warmup=${MT3_WARMUP}"
exec python -m uvicorn mt3_gpu_worker:app --host 0.0.0.0 --port "$PORT"
