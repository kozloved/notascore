import assert from "node:assert/strict";
import test from "node:test";

import {
  ALGORITHM_VERSION_CURRENT,
  ALGORITHM_VERSION_READABLE_V2,
  ALGORITHM_VERSION_READABLE_V3,
  ALGORITHM_VERSION_USER_READABLE,
  algorithmVersionLabel,
  isCurrentReadableEngine,
  needsCurrentReadableEngine,
  patchForCurrentReadable,
  patchForInterpretation,
  detectedFeelSummary,
  patchForReadableGapStyle,
  readableGapStyle,
  rhythmicFeelLabel,
} from "./notation-style.ts";

test("internal version labels are not Standard or Experimental", () => {
  assert.equal(algorithmVersionLabel(ALGORITHM_VERSION_CURRENT), "Legacy engine");
  assert.equal(
    algorithmVersionLabel(ALGORITHM_VERSION_READABLE_V2),
    "Saved Readable engine"
  );
  assert.equal(
    algorithmVersionLabel(ALGORITHM_VERSION_READABLE_V3),
    "Readable engine"
  );
});

test("user-facing Readable pins the current Readable engine", () => {
  assert.deepEqual(patchForInterpretation("readable"), {
    interpretation: "readable",
    algorithm_version: ALGORITHM_VERSION_USER_READABLE,
  });
  assert.equal(ALGORITHM_VERSION_USER_READABLE, ALGORITHM_VERSION_READABLE_V3);
  assert.deepEqual(patchForInterpretation("literal"), {
    interpretation: "literal",
  });
});

test("saved Readable can apply the current engine without a mode round trip", () => {
  assert.equal(
    needsCurrentReadableEngine({
      interpretation: "readable",
      algorithm_version: ALGORITHM_VERSION_CURRENT,
    }),
    true
  );
  assert.equal(
    needsCurrentReadableEngine({
      interpretation: "readable",
      algorithm_version: ALGORITHM_VERSION_READABLE_V2,
    }),
    true
  );
  assert.equal(
    isCurrentReadableEngine({
      interpretation: "readable",
      algorithm_version: ALGORITHM_VERSION_USER_READABLE,
    }),
    true
  );
  assert.deepEqual(patchForCurrentReadable(), {
    interpretation: "readable",
    algorithm_version: ALGORITHM_VERSION_USER_READABLE,
    apply_current_readable: true,
  });
});

test("legacy Readable keeps tiny gaps; current Readable fills them", () => {
  assert.equal(
    readableGapStyle({
      interpretation: "readable",
      algorithm_version: ALGORITHM_VERSION_CURRENT,
    }),
    "current"
  );
  assert.deepEqual(patchForReadableGapStyle("current"), {
    interpretation: "readable",
    algorithm_version: ALGORITHM_VERSION_CURRENT,
  });
  assert.equal(
    readableGapStyle({
      interpretation: "readable",
      algorithm_version: ALGORITHM_VERSION_USER_READABLE,
    }),
    "fill_tiny_gaps"
  );
});

test("Literal never looks like the Readable fill preset", () => {
  assert.equal(
    readableGapStyle({
      interpretation: "literal",
      algorithm_version: ALGORITHM_VERSION_USER_READABLE,
    }),
    "current"
  );
});

test("feel labels stay musician-facing", () => {
  assert.equal(rhythmicFeelLabel("swing_eighths"), "Swing eighths");
  assert.equal(rhythmicFeelLabel("straight"), "Straight");
});

test("detected feel summary is optional and evidence-gated", () => {
  assert.equal(
    detectedFeelSummary({
      rhythmic_feel: "swing_eighths",
      maps_written_timing: true,
      confidence: 0.9,
    }),
    "Swing detected — shown using conventional eighth-note notation."
  );
  assert.equal(
    detectedFeelSummary({
      rhythmic_feel: "swing_sixteenths",
      maps_written_timing: true,
      confidence: 0.9,
    }),
    "Swing 16ths detected — shown using conventional sixteenth-note notation."
  );
  assert.equal(
    detectedFeelSummary({
      rhythmic_feel: "swing_eighths",
      maps_written_timing: false,
      confidence: 0.9,
    }),
    null
  );
  assert.equal(
    detectedFeelSummary({
      rhythmic_feel: "straight",
      maps_written_timing: false,
    }),
    null
  );
});
