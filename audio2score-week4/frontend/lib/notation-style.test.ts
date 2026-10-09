import assert from "node:assert/strict";
import test from "node:test";

import {
  ALGORITHM_VERSION_CURRENT,
  ALGORITHM_VERSION_READABLE_V2,
  algorithmVersionLabel,
  detectedFeelSummary,
  patchForReadableGapStyle,
  readableGapStyle,
  rhythmicFeelLabel,
} from "./notation-style.ts";

test("algorithm version labels stay Standard vs Experimental", () => {
  assert.equal(algorithmVersionLabel(ALGORITHM_VERSION_CURRENT), "Standard");
  assert.equal(
    algorithmVersionLabel(ALGORITHM_VERSION_READABLE_V2),
    "Experimental"
  );
});

test("defaults and Readable stay on the current algorithm", () => {
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
});

test("Fill tiny gaps is an explicit readable-v2 opt-in", () => {
  assert.equal(
    readableGapStyle({
      interpretation: "readable",
      algorithm_version: ALGORITHM_VERSION_READABLE_V2,
    }),
    "fill_tiny_gaps"
  );
  assert.deepEqual(patchForReadableGapStyle("fill_tiny_gaps"), {
    interpretation: "readable",
    algorithm_version: ALGORITHM_VERSION_READABLE_V2,
  });
});

test("Literal never looks like the v2 preset", () => {
  assert.equal(
    readableGapStyle({
      interpretation: "literal",
      algorithm_version: ALGORITHM_VERSION_READABLE_V2,
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
