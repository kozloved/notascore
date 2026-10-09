import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { allocateSoundingLanes, applyPlaybackTiming, type PlaybackNote, type SwingSpan } from "./swing-playback.ts";

const PARITY = JSON.parse(
  readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../../backend/evaluation/swing_playback_parity.json"),
    "utf8"
  )
) as {
  tick_tolerance_ppq: number;
  beat_tolerance: number;
  cases: Array<{
    name: string;
    notes: Array<PlaybackNote & { id: string; pitch: number }>;
    spans: SwingSpan[];
    expected: Array<{ id: string; start: number; duration: number }>;
  }>;
};

const BEAT_TOL = Number(PARITY.beat_tolerance || 1e-9);
const PPQ = Number(PARITY.tick_tolerance_ppq || 480);

function ticks(beat: number): number {
  return Math.round(beat * PPQ);
}

for (const fixture of PARITY.cases) {
  test(`parity ${fixture.name} onsets and releases`, () => {
    const sounded = applyPlaybackTiming(fixture.notes, fixture.spans);
    const byId = new Map(sounded.map((note) => [note.id, note]));
    assert.ok(fixture.expected.length, fixture.name);
    for (const row of fixture.expected) {
      const got = byId.get(row.id);
      assert.ok(got, row.id);
      assert.ok(Math.abs(got.start - row.start) <= BEAT_TOL, `${row.id} start ${got.start} != ${row.start}`);
      assert.ok(
        Math.abs(got.start + got.duration - (row.start + row.duration)) <= BEAT_TOL,
        `${row.id} end`
      );
      assert.equal(ticks(got.start), ticks(row.start), `${row.id} onset ticks`);
      assert.equal(ticks(got.start + got.duration), ticks(row.start + row.duration), `${row.id} release ticks`);
    }
  });
}

test("sounding lanes keep overlapping unisons", () => {
  const notes = [
    { id: "held", start: 0, duration: 5, pitch: 59 },
    { id: "later", start: 4.9, duration: 0.5, pitch: 59 },
  ];
  const lanes = allocateSoundingLanes(notes);
  assert.notEqual(lanes[0], lanes[1]);
});
