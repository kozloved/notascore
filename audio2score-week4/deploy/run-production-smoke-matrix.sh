#!/usr/bin/env bash
# Run whichever local production-smoke fixtures exist.
#
# Missing files are SKIP. A present fixture that fails processing is FAIL.
# Does not judge notation quality.
#
# Usage:
#   BASE_URL=https://notascore.com/api ./deploy/run-production-smoke-matrix.sh
#   FIXTURE_DIR=/path/to/wavs BASE_URL=https://notascore.com/api \
#     ./deploy/run-production-smoke-matrix.sh
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${BASE_URL:-https://notascore.com/api}"
FIXTURE_DIR="${FIXTURE_DIR:-$ROOT_DIR/backend/evaluation/production_smoke}"
SMOKE="$ROOT_DIR/deploy/smoke-nextgen-live.sh"

CASES=(
  "solo-piano.wav:solo:solo-piano"
  "solo-violin.wav:solo:solo-violin"
  "polyphonic-piano.wav:polyphonic:polyphonic-piano"
  "full-song.wav:polyphonic:full-song"
  "rubato-piano.wav:polyphonic:rubato"
  "short-rests.wav:polyphonic:short-rests"
  "barline-sustain.wav:polyphonic:barline-sustain"
  "repeated-notes.wav:polyphonic:repeated-notes"
)

pass=0
fail=0
skip=0
results=()

echo "NotaScore Next-Gen production smoke matrix"
echo "BASE_URL=$BASE_URL"
echo "FIXTURE_DIR=$FIXTURE_DIR"
echo

for spec in "${CASES[@]}"; do
  IFS=':' read -r filename mode case_label <<<"$spec"
  path="$FIXTURE_DIR/$filename"
  if [ ! -f "$path" ]; then
    echo "SKIP  $case_label  ($filename not found)"
    results+=("SKIP  $case_label")
    skip=$((skip + 1))
    continue
  fi
  echo "RUN   $case_label  mode=$mode  file=$path"
  if MODE="$mode" CASE="$case_label" BASE_URL="$BASE_URL" "$SMOKE" "$path"; then
    echo "PASS  $case_label"
    results+=("PASS  $case_label")
    pass=$((pass + 1))
  else
    echo "FAIL  $case_label"
    results+=("FAIL  $case_label")
    fail=$((fail + 1))
  fi
  echo
done

echo "=============================="
echo "PASS / FAIL / SKIP summary"
echo "=============================="
for row in "${results[@]}"; do
  echo "$row"
done
echo
echo "PASS=$pass FAIL=$fail SKIP=$skip"

if [ "$fail" -gt 0 ]; then
  exit 1
fi
exit 0
