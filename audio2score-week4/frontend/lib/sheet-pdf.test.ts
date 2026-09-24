import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import { assembleScorePdf, PDF_OPTIONS } from "./sheet-pdf.js";

const require = createRequire(import.meta.url);
const { jsPDF } = require("jspdf");

const TINY_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==";

test("assembleScorePdf is the production jsPDF path", () => {
  assert.deepEqual(PDF_OPTIONS, { orientation: "portrait", unit: "pt", format: "a4" });
  const pdf = assembleScorePdf([TINY_PNG, TINY_PNG], jsPDF);
  assert.equal(pdf.getNumberOfPages(), 2);
  const bytes = pdf.output("arraybuffer");
  assert.ok(bytes.byteLength > 100);
  const header = Buffer.from(bytes).subarray(0, 4).toString("latin1");
  assert.equal(header, "%PDF");
});

test("assembleScorePdf refuses an empty preview", () => {
  assert.throws(() => assembleScorePdf([], jsPDF), /Sheet preview is not ready yet/);
});
