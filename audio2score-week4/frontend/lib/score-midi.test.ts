import assert from "node:assert/strict";
import test from "node:test";

import { changeArticulation } from "./score-editor.ts";
import { playbackDurationBeats, STACCATO_PLAYBACK_FRACTION } from "./score-midi.ts";

test("score playback shortens staccato to half the written value", () => {
  assert.equal(STACCATO_PLAYBACK_FRACTION, 0.5);
  assert.equal(playbackDurationBeats({ duration: 1, articulation: null }), 1);
  assert.equal(playbackDurationBeats({ duration: 1, articulation: "staccato" }), 0.5);
  assert.equal(playbackDurationBeats({ duration: 2, articulation: "tenuto" }), 2);
});

test("clearing inferred staccato restores full written playback", () => {
  const notes = [
    {
      id: "n-0000",
      source_note_id: "src",
      pitch: 72,
      start: 0,
      duration: 1,
      velocity: 80,
      track: 0,
      voice: 0,
      articulation: "staccato",
      articulation_source: "inferred",
    },
  ];
  const cleared = changeArticulation(notes, "n-0000", null);
  assert.equal(cleared[0].articulation, null);
  assert.equal(cleared[0].articulation_source, "user_edit");
  assert.equal(playbackDurationBeats(cleared[0]), 1);
});
