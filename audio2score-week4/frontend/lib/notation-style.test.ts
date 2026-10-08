import assert from "node:assert/strict";
import test from "node:test";

import {
  ALGORITHM_VERSION_CURRENT,
  ALGORITHM_VERSION_READABLE_V2,
  ALGORITHM_VERSION_USER_READABLE,
  algorithmVersionLabel,
  patchForInterpretation,
  patchForReadableGapStyle,
  readableGapStyle,
} from "./notation-style.ts";

test("internal version labels are not Standard or Experimental", () => {
  assert.equal(algorithmVersionLabel(ALGORITHM_VERSION_CURRENT), "Legacy engine");
  assert.equal(
    algorithmVersionLabel(ALGORITHM_VERSION_READABLE_V2),
    "Readable engine"
  );
});

test("user-facing Readable pins the current Readable engine", () => {
  assert.deepEqual(patchForInterpretation("readable"), {
    interpretation: "readable",
    algorithm_version: ALGORITHM_VERSION_USER_READABLE,
  });
  assert.equal(ALGORITHM_VERSION_USER_READABLE, ALGORITHM_VERSION_READABLE_V2);
  assert.deepEqual(patchForInterpretation("literal"), {
    interpretation: "literal",
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
      algorithm_version: ALGORITHM_VERSION_READABLE_V2,
    }),
    "fill_tiny_gaps"
  );
});

test("Literal never looks like the Readable fill preset", () => {
  assert.equal(
    readableGapStyle({
      interpretation: "literal",
      algorithm_version: ALGORITHM_VERSION_READABLE_V2,
    }),
    "current"
  );
});
