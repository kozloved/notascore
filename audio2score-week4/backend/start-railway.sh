#!/usr/bin/env bash
# Railway CPU service: FastAPI + RQ worker in one container so Solo jobs
# share local disk (uploads / results / sqlite) without a shared volume.
set -euo pipefail
cd "$(dirname "$0")"

export DATABASE_URL="${DATABASE_URL:-sqlite:////data/audio2score.db}"
export UPLOAD_DIR="${UPLOAD_DIR:-/data/uploads}"
export RESULTS_DIR="${RESULTS_DIR:-/data/results}"
export TEMP_DIR="${TEMP_DIR:-/data/tmp}"
PORT="${PORT:-8000}"

mkdir -p "$UPLOAD_DIR" "$RESULTS_DIR" "$TEMP_DIR" /data

echo "[railway] starting RQ worker"
(
  while true; do
    python worker.py || true
    echo "[railway] worker exited; restarting in 3s"
    sleep 3
  done
) &

echo "[railway] starting API on [::]:${PORT}"
# Bind IPv6 so Railway private networking (frontend → backend) works.
exec uvicorn main:app --host "::" --port "$PORT"
