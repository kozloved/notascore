#!/usr/bin/env bash
# Render CPU service: FastAPI + RQ worker in one container so Solo jobs
# share local disk (uploads / results / sqlite). Render disks cannot be
# mounted on two services.
set -euo pipefail
cd "$(dirname "$0")"

export DATABASE_URL="${DATABASE_URL:-sqlite:////data/audio2score.db}"
export UPLOAD_DIR="${UPLOAD_DIR:-/data/uploads}"
export RESULTS_DIR="${RESULTS_DIR:-/data/results}"
export TEMP_DIR="${TEMP_DIR:-/data/tmp}"
PORT="${PORT:-8000}"

mkdir -p "$UPLOAD_DIR" "$RESULTS_DIR" "$TEMP_DIR" /data

echo "[web] starting RQ worker"
(
  while true; do
    python worker.py || true
    echo "[web] worker exited; restarting in 3s"
    sleep 3
  done
) &

echo "[web] starting API on 0.0.0.0:${PORT}"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
