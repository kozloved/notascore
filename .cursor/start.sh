#!/usr/bin/env bash
# Per-boot startup for the NotaScore / Audio2Score app.
# Brings up Redis (backs the RQ transcription queue) and launches the three
# long-running services (API, worker, Next.js dev server) as background
# processes. Idempotent: existing/healthy processes are left running.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/audio2score-week4"

# --- Redis ---
if redis-cli ping >/dev/null 2>&1; then
  echo "Redis already running"
else
  echo "Starting Redis..."
  redis-server --daemonize yes --save "" --appendonly no --dir /tmp
  for _ in $(seq 1 20); do
    redis-cli ping >/dev/null 2>&1 && break
    sleep 0.5
  done
  redis-cli ping >/dev/null 2>&1 || { echo "ERROR: Redis did not start" >&2; exit 1; }
fi

# --- App services ---
start_svc() {
  local name="$1" dir="$2" cmd="$3"
  local pidfile="/tmp/a2s-${name}.pid" log="/tmp/a2s-${name}.log"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; then
    echo "${name} already running (pid $(cat "$pidfile"))"
    return 0
  fi
  ( cd "$dir" && setsid bash -lc "$cmd" >"$log" 2>&1 < /dev/null & echo $! >"$pidfile" )
  echo "started ${name} (log ${log})"
}

start_svc api      "$APP_DIR/backend"  ".venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000"
start_svc worker   "$APP_DIR/backend"  ".venv/bin/python worker.py"
start_svc frontend "$APP_DIR/frontend" "npm run dev"

# Give the API a moment to become ready (it does not load TensorFlow, so it is fast).
for _ in $(seq 1 30); do
  curl -sf http://localhost:8000/health >/dev/null 2>&1 && { echo "API is up"; break; }
  sleep 1
done

echo "start.sh complete"
