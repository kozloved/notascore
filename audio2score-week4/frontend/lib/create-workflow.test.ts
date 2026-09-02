import assert from "node:assert/strict";
import test from "node:test";

import {
  fileExtension,
  isMidiFilename,
  validateRecording,
  friendlyUploadError,
} from "./files.ts";
import { uploadMode } from "./modes.ts";
import {
  mapBackendStatus,
  currentStage,
  headlineForJob,
  chipLabel,
} from "./job-ux.ts";

test("accepts supported audio and midi extensions", () => {
  assert.equal(fileExtension("Idea.WAV"), ".wav");
  assert.equal(isMidiFilename("line.mid"), true);
  const ok = validateRecording({ name: "idea.mp3", size: 1024 } as File);
  assert.deepEqual(ok, { ok: true, midi: false });
});

test("rejects unsupported types and oversized files", () => {
  const bad = validateRecording({ name: "notes.pdf", size: 10 } as File);
  assert.deepEqual(bad, { ok: false, reason: "type" });
  const huge = validateRecording({
    name: "idea.wav",
    size: 26 * 1024 * 1024,
  } as File);
  assert.deepEqual(huge, { ok: false, reason: "size" });
});

test("maps backend job states without exposing enums", () => {
  assert.equal(mapBackendStatus("queued"), "queued");
  assert.equal(mapBackendStatus("processing"), "processing");
  assert.equal(mapBackendStatus("completed"), "completed");
  assert.equal(mapBackendStatus("failed"), "failed");
  assert.equal(headlineForJob("queued", 0), "Preparing your score…");
  assert.equal(headlineForJob("failed", 0), "We couldn’t create your score.");
  assert.equal(headlineForJob("completed", 100), "Your score is ready.");
  assert.equal(chipLabel("completed"), "Ready");
  assert.equal(currentStage("processing", 10), "listening");
  assert.equal(currentStage("processing", 30), "notes");
  assert.equal(currentStage("processing", 50), "rhythm");
  assert.equal(currentStage("processing", 80), "writing");
});

test("hides raw upload errors", () => {
  const message = friendlyUploadError(
    new Error("Polyphonic mode is not configured. Set MT3_ENDPOINT")
  );
  assert.equal(message.includes("MT3_ENDPOINT"), false);
  assert.match(message, /polyphonic isn’t available/i);
  const typeMessage = friendlyUploadError(new Error("Invalid file type"));
  assert.match(typeMessage, /isn’t supported/i);
  assert.equal(typeMessage.includes("transcribed"), false);
});

test("create UI sends polyphonic unless the file is MIDI", () => {
  assert.equal(uploadMode({ selected: "solo", midi: false }), "solo");
  assert.equal(uploadMode({ selected: "polyphonic", midi: false }), "polyphonic");
  assert.equal(uploadMode({ selected: "polyphonic", midi: true }), "solo");
});
