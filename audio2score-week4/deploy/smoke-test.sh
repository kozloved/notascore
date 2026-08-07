#!/usr/bin/env bash
# End-to-end API smoke test against a running deploy.
# Usage:
#   BASE_URL=https://notascore.com/api ./deploy/smoke-test.sh [path/to/audio.wav]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${BASE_URL:-https://notascore.com/api}"
AUDIO="${1:-$ROOT_DIR/backend/test_tone.wav}"

if [ ! -f "$AUDIO" ]; then
  echo "Audio file not found: $AUDIO" >&2
  exit 1
fi

echo "==> health"
curl -fsS "$BASE_URL/health"
echo

echo "==> upload $AUDIO"
RESP=$(curl -fsS -F "file=@${AUDIO};type=audio/wav" "$BASE_URL/upload")
echo "$RESP"
JOB_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['job_id'])" "$RESP")

echo "==> poll job $JOB_ID"
for i in $(seq 1 90); do
  STATUS=$(curl -fsS "$BASE_URL/jobs/$JOB_ID")
  STATE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['status'])" "$STATUS")
  PROG=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('progress'))" "$STATUS")
  ERR=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('error'))" "$STATUS")
  echo "[$i] status=$STATE progress=$PROG error=$ERR"
  if [ "$STATE" = "completed" ] || [ "$STATE" = "failed" ]; then
    break
  fi
  sleep 5
done

if [ "$STATE" != "completed" ]; then
  echo "Job did not complete: $STATUS" >&2
  exit 1
fi

OUT="${TMPDIR:-/tmp}/notascore-${JOB_ID}.musicxml"
echo "==> download -> $OUT"
curl -fsS -o "$OUT" "$BASE_URL/jobs/$JOB_ID/result"
head -c 200 "$OUT"
echo
echo "OK: $(wc -c < "$OUT") bytes"
