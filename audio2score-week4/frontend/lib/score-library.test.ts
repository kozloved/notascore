import assert from "node:assert/strict";
import test from "node:test";

import { chipLabel } from "./job-ux.ts";
import {
  sortScores,
  titleFromFilename,
} from "./score-meta.ts";

test("derives titles from filenames", () => {
  assert.equal(titleFromFilename("my-piano-idea.wav"), "My Piano Idea");
  assert.equal(titleFromFilename(""), "Untitled score");
});

test("sorts scores newest oldest and name", () => {
  const items = [
    { title: "Bravo", created_at: "2026-01-02T00:00:00Z" },
    { title: "Alpha", created_at: "2026-01-03T00:00:00Z" },
  ];
  assert.equal(sortScores(items, "newest")[0].title, "Alpha");
  assert.equal(sortScores(items, "oldest")[0].title, "Bravo");
  assert.equal(sortScores(items, "name")[0].title, "Alpha");
});

test("library chips stay musician-facing", () => {
  assert.equal(chipLabel("completed"), "Ready");
  assert.equal(chipLabel("failed"), "Failed");
  assert.equal(chipLabel("processing"), "Processing…");
});
