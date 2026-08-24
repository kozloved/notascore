#!/usr/bin/env bash
# Start the MR-MT3 HTTP worker. Bind 0.0.0.0 so RunPod / a public URL can reach it.
set -euo pipefail
cd "$(dirname "$0")"
export MT3_MODEL="${MT3_MODEL:-mr_mt3}"
PORT="${PORT:-8090}"
echo "Starting MT3 worker on 0.0.0.0:${PORT} model=${MT3_MODEL}"
exec python -m uvicorn mt3_gpu_worker:app --host 0.0.0.0 --port "$PORT"
