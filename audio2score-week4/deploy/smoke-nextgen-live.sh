#!/usr/bin/env bash
# Verify the first Next-Gen production cutover (orchestrator live, federation OFF).
#
# Usage:
#   MODE=solo BASE_URL=https://notascore.com/api ./deploy/smoke-nextgen-live.sh ./piano.wav
#   MODE=polyphonic CASE=full-song BASE_URL=https://notascore.com/api \
#     ./deploy/smoke-nextgen-live.sh ./full-song.wav
#
# MODE defaults to solo. CASE is a diagnostic label only (not pipeline routing).
# Does not embed authentication credentials.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${BASE_URL:-https://notascore.com/api}"
AUDIO="${1:-}"
MODE="${MODE:-solo}"
CASE="${CASE:-}"
export PYTHONPATH="${ROOT_DIR}/backend${PYTHONPATH:+:$PYTHONPATH}"

smoke_py() {
  python3 -m evaluation.production_smoke.check "$@"
}

MODE="$(smoke_py resolve-mode "$MODE")"
echo "smoke mode: ${MODE}"
if [ -n "$CASE" ]; then
  echo "smoke case: ${CASE} (diagnostic label only; does not change routing)"
fi

echo "==> health $BASE_URL/health"
HEALTH=$(curl -fsS "$BASE_URL/health")
echo "$HEALTH"
HEALTH_JSON="${TMPDIR:-/tmp}/notascore-health-$$.json"
printf '%s' "$HEALTH" > "$HEALTH_JSON"
trap 'rm -f "$HEALTH_JSON"' EXIT
printf '%s' "$HEALTH" | smoke_py check-health --mode "$MODE"

if [ -z "$AUDIO" ]; then
  echo "OK: health cutover checks passed (no audio fixture supplied)"
  exit 0
fi

if [ ! -f "$AUDIO" ]; then
  echo "Audio file not found: $AUDIO" >&2
  exit 1
fi

echo "==> upload $AUDIO mode=${MODE}"
RESP=$(curl -fsS -F "file=@${AUDIO};type=audio/wav" -F "mode=${MODE}" "$BASE_URL/upload")
echo "$RESP"
JOB_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['job_id'])" "$RESP")
echo "job_id=${JOB_ID}"

echo "==> poll job $JOB_ID"
STATE=""
STATUS=""
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

printf '%s' "$STATUS" | smoke_py check-job --mode "$MODE"

echo "==> artifacts"
ART=$(curl -fsS "$BASE_URL/jobs/$JOB_ID/artifacts")
echo "$ART"
python3 - "$ART" "$JOB_ID" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
job_id = sys.argv[2]
names = {row.get("filename") or row.get("name") for row in payload.get("artifacts") or []}
required = {
    f"{job_id}.raw.mid",
    f"{job_id}.score.mid",
    f"{job_id}.musicxml",
    f"{job_id}.manifest.json",
    f"{job_id}.provenance.json",
    f"{job_id}.tempo.json",
}
missing = sorted(required - names)
if missing:
    raise SystemExit("missing required artifacts: " + ", ".join(missing))
print("required artifacts present; fused/stems may be absent")
PY

WORKDIR="${TMPDIR:-/tmp}/notascore-nextgen-${JOB_ID}"
mkdir -p "$WORKDIR"
for kind in raw.mid score.mid manifest.json provenance.json tempo.json musicxml; do
  name="${JOB_ID}.${kind}"
  echo "==> download $name"
  curl -fsS -o "$WORKDIR/$name" "$BASE_URL/jobs/$JOB_ID/artifacts/$name"
done

python3 - "$WORKDIR" "$JOB_ID" "$MODE" "$CASE" "$HEALTH_JSON" <<'PY'
import json, sys
from pathlib import Path

from evaluation.production_smoke.check import (
    assert_live_provenance,
    format_smoke_report,
    sha256_file,
)

root = Path(sys.argv[1])
job_id = sys.argv[2]
mode = sys.argv[3]
case = sys.argv[4]
health = json.loads(Path(sys.argv[5]).read_text())
raw_path = root / f"{job_id}.raw.mid"
score_path = root / f"{job_id}.score.mid"
raw = raw_path.read_bytes()
score = score_path.read_bytes()
if not raw.startswith(b"MThd"):
    raise SystemExit("raw.mid is not a MIDI file")
if not score.startswith(b"MThd"):
    raise SystemExit("score.mid is not a MIDI file")
if raw == score:
    raise SystemExit("raw.mid must not equal score.mid")
prov = json.loads((root / f"{job_id}.provenance.json").read_text())
assert_live_provenance(prov, mode=mode)
artifacts = {
    "raw.mid": raw_path.is_file(),
    "score.mid": score_path.is_file(),
    "musicxml": (root / f"{job_id}.musicxml").is_file(),
    "manifest": (root / f"{job_id}.manifest.json").is_file(),
    "provenance": (root / f"{job_id}.provenance.json").is_file(),
    "tempo": (root / f"{job_id}.tempo.json").is_file(),
}
print(
    format_smoke_report(
        case=case,
        mode=mode,
        health=health,
        provenance=prov,
        raw_sha=sha256_file(raw_path),
        score_sha=sha256_file(score_path),
        artifacts=artifacts,
        result="PASS",
    ),
    end="",
)
PY
