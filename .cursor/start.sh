#!/usr/bin/env bash
# Per-boot runtime setup: bring up Redis, which backs the RQ transcription
# queue. The API, worker and frontend run as long-lived `terminals`.
# Idempotent: does nothing if Redis is already responding.
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
