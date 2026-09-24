import assert from "node:assert/strict";
import test from "node:test";

import {
  ALGORITHM_VERSION_CURRENT,
  ALGORITHM_VERSION_READABLE_V2,
  patchForReadableGapStyle,
  readableGapStyle,
} from "./notation-style.ts";

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
