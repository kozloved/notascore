import assert from "node:assert/strict";
import test from "node:test";

import {
  allocateSoundingLanes,
  applyPlaybackTiming,
  mapBeatThroughSwing,
  performedOffbeatFraction,
} from "./swing-playback.ts";

test("2:1 written eighths sound at the performed offbeat", () => {
  const ratio = 2;
  assert.equal(performedOffbeatFraction(ratio), 2 / 3);
  assert.ok(Math.abs(mapBeatThroughSwing(0.5, 1, ratio, true) - 2 / 3) < 1e-9);
  const notes = [
    { start: 0, duration: 0.5 },
    { start: 0.5, duration: 0.5 },
  ];
  const swung = applyPlaybackTiming(notes, [
    {
      start_beat: 0,
      end_beat: 4,
      feel: "swing_eighths",
      subdivision_unit: 0.5,
      ratio: 2,
      maps_written_timing: true,
    },
  ]);
  assert.ok(Math.abs(swung[0].start - 0) < 1e-9);
  assert.ok(Math.abs(swung[1].start - 2 / 3) < 1e-9);
});

test("straight spans do not move written offbeats", () => {
  const notes = [
    { start: 0, duration: 0.5 },
    { start: 0.5, duration: 0.5 },
  ];
  const out = applyPlaybackTiming(notes, [
    { start_beat: 0, end_beat: 4, feel: "straight", maps_written_timing: false },
  ]);
  assert.equal(out[1].start, 0.5);
});

test("long sustains are not reverse-mapped under light sixteenth swing", () => {
  const notes = [
    { start: 3.75, duration: 5, performed_start_beat: 3.75, performed_duration_beats: 5 },
    { start: 8.75, duration: 0.25, performed_start_beat: 8.75, performed_duration_beats: 0.25 },
  ];
  const out = applyPlaybackTiming(notes, [
    {
      start_beat: 0,
      end_beat: 16,
      feel: "swing_sixteenths",
      subdivision_unit: 0.25,
      ratio: 1.15,
      maps_written_timing: true,
    },
  ]);
  assert.equal(out[0].start, 3.75);
  assert.ok(out[0].start + out[0].duration <= out[1].start + 1e-9);
});

test("a long swung offbeat maps its onset and keeps the written release", () => {
  const notes = [
    {
      id: "long",
      start: 0.5,
      duration: 3.5,
      pitch: 74,
      performed_start_beat: 2 / 3,
      performed_duration_beats: 10 / 3,
      stream_key: "|right|0",
    },
  ];
  const out = applyPlaybackTiming(notes, [
    {
      start_beat: 0,
      end_beat: 8,
      feel: "swing_eighths",
      subdivision_unit: 0.5,
      ratio: 2,
      maps_written_timing: true,
    },
  ]);
  assert.ok(Math.abs(out[0].start - 2 / 3) < 1e-9);
  assert.ok(Math.abs(out[0].start + out[0].duration - 4) < 1e-9);
});

test("overlapping unisons get separate sounding lanes", () => {
  const lanes = allocateSoundingLanes([
    { id: "held", start: 0, duration: 5, pitch: 59 },
    { id: "later", start: 4.9, duration: 0.5, pitch: 59 },
  ]);
  assert.notEqual(lanes[0], lanes[1]);
});

test("literal spans with maps_written_timing false stay put", () => {
  const notes = [{ start: 0.5, duration: 0.5 }];
  const out = applyPlaybackTiming(notes, [
    {
      start_beat: 0,
      end_beat: 4,
      feel: "swing_eighths",
      ratio: 2,
      maps_written_timing: false,
    },
  ]);
  assert.equal(out[0].start, 0.5);
});
