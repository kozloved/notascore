#!/usr/bin/env bash
# Per-boot startup: bring up Redis, which backs the RQ transcription queue.
# The API, worker and Next.js dev server run as long-lived `terminals`
# (see .cursor/environment.json). Idempotent: no-op if Redis already responds.
set -euo pipefail

if redis-cli ping >/dev/null 2>&1; then
  echo "Redis already running"
  exit 0
fi

echo "Starting Redis..."
redis-server --daemonize yes --save "" --appendonly no --dir /tmp

for _ in $(seq 1 20); do
  if redis-cli ping >/dev/null 2>&1; then
    echo "Redis is up"
    exit 0
  fi
  sleep 0.5
done

echo "ERROR: Redis did not become ready in time" >&2
exit 1
