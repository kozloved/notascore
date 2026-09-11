#!/usr/bin/env bash
# Verify the first Next-Gen production cutover (orchestrator live, federation OFF).
#
# Usage:
#   BASE_URL=https://notascore.com/api ./deploy/smoke-nextgen-live.sh
#   BASE_URL=https://notascore.com/api ./deploy/smoke-nextgen-live.sh ./fixtures/piano.wav
#
# Does not embed authentication credentials. Anonymous upload is used only when
# an audio fixture path is supplied.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${BASE_URL:-https://notascore.com/api}"
AUDIO="${1:-}"

python_health_check() {
  python3 - "$1" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
ng = payload.get("nextgen") or {}
errors = []
if ng.get("pipeline_mode") != "live":
    errors.append(f"pipeline_mode={ng.get('pipeline_mode')!r} (expected live)")
if ng.get("orchestrator_active") is not True:
    errors.append(f"orchestrator_active={ng.get('orchestrator_active')!r} (expected true)")
for key in (
    "separation_enabled",
    "stem_transcription_enabled",
    "fusion_enabled",
    "ensemble_render_enabled",
):
    if ng.get(key) is not False:
        errors.append(f"{key}={ng.get(key)!r} (expected false for first cutover)")
if errors:
    print("health nextgen check failed:", file=sys.stderr)
    for row in errors:
        print(f"  {row}", file=sys.stderr)
    sys.exit(1)
print("health nextgen: pipeline_mode=live orchestrator_active=true federation=off")
PY
}

echo "==> health $BASE_URL/health"
HEALTH=$(curl -fsS "$BASE_URL/health")
echo "$HEALTH"
python_health_check "$HEALTH"

if [ -z "$AUDIO" ]; then
  echo "OK: health cutover checks passed (no audio fixture supplied)"
  exit 0
fi

if [ ! -f "$AUDIO" ]; then
  echo "Audio file not found: $AUDIO" >&2
  exit 1
fi

echo "==> upload $AUDIO"
RESP=$(curl -fsS -F "file=@${AUDIO};type=audio/wav" "$BASE_URL/upload")
echo "$RESP"
JOB_ID=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['job_id'])" "$RESP")

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
# Federation artifacts are optional on the first cutover.
print("required artifacts present; fused/stems may be absent")
PY

WORKDIR="${TMPDIR:-/tmp}/notascore-nextgen-${JOB_ID}"
mkdir -p "$WORKDIR"
for kind in raw.mid score.mid manifest.json provenance.json tempo.json musicxml; do
  name="${JOB_ID}.${kind}"
  echo "==> download $name"
  curl -fsS -o "$WORKDIR/$name" "$BASE_URL/jobs/$JOB_ID/artifacts/$name"
done

python3 - "$WORKDIR" "$JOB_ID" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
job_id = sys.argv[2]
raw = (root / f"{job_id}.raw.mid").read_bytes()
score = (root / f"{job_id}.score.mid").read_bytes()
if not raw.startswith(b"MThd"):
    raise SystemExit("raw.mid is not a MIDI file")
if not score.startswith(b"MThd"):
    raise SystemExit("score.mid is not a MIDI file")
if raw == score:
    raise SystemExit("raw.mid must not equal score.mid")
prov = json.loads((root / f"{job_id}.provenance.json").read_text())
if prov.get("pipeline_mode") != "live":
    raise SystemExit(f"provenance pipeline_mode={prov.get('pipeline_mode')!r}")
if prov.get("orchestrator") != "nextgen":
    raise SystemExit(f"provenance orchestrator={prov.get('orchestrator')!r}")
print("raw sha256", hashlib.sha256(raw).hexdigest())
print("score sha256", hashlib.sha256(score).hexdigest())
print("OK: live job artifacts downloaded")
PY
