import assert from "node:assert/strict";
import test from "node:test";

import { changeArticulation } from "./score-editor.ts";
import { playbackDurationBeats, STACCATO_PLAYBACK_FRACTION } from "./score-midi.ts";
import { applyPlaybackTiming } from "./swing-playback.ts";

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

test("staccato shortens swung sounding duration without moving the mapped onset", () => {
  const span = {
    start_beat: 0,
    end_beat: 4,
    feel: "swing_eighths",
    subdivision_unit: 0.5,
    ratio: 2,
    maps_written_timing: true,
  };
  const [sounded] = applyPlaybackTiming(
    [
      {
        start: 0.5,
        duration: 0.5,
        articulation: "staccato",
        performed_start_beat: 2 / 3,
        stream_key: "|right|0",
      },
    ],
    [span]
  );
  assert.ok(Math.abs(sounded.start - 2 / 3) < 1e-9);
  assert.ok(Math.abs(sounded.duration - 1 / 3) < 1e-9);
  assert.ok(Math.abs(playbackDurationBeats(sounded) - 1 / 6) < 1e-9);
});
