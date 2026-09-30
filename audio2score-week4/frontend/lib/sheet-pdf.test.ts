import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import {
  assembleScorePdf,
  fitImageRect,
  PDF_MARGIN_PT,
  PDF_OPTIONS,
  PRINT_SVG_WIDTH,
} from "./sheet-pdf.js";

const require = createRequire(import.meta.url);
const { jsPDF } = require("jspdf");

const TINY_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==";

test("assembleScorePdf is the production jsPDF path", () => {
  assert.deepEqual(PDF_OPTIONS, { orientation: "portrait", unit: "pt", format: "a4" });
  const pdf = assembleScorePdf(
    [
      { dataUrl: TINY_PNG, w: 720, h: 400 },
      { dataUrl: TINY_PNG, w: 720, h: 200 },
    ],
    jsPDF
  );
  assert.equal(pdf.getNumberOfPages(), 2);
  const bytes = pdf.output("arraybuffer");
  assert.ok(bytes.byteLength > 100);
  const header = Buffer.from(bytes).subarray(0, 4).toString("latin1");
  assert.equal(header, "%PDF");
});

test("assembleScorePdf refuses an empty preview", () => {
  assert.throws(() => assembleScorePdf([], jsPDF), /Sheet preview is not ready yet/);
});

test("fitImageRect preserves aspect ratio and applies margins", () => {
  const pageW = 595.28;
  const pageH = 841.89;
  const wide = fitImageRect(1000, 400, pageW, pageH);
  assert.equal(wide.y, PDF_MARGIN_PT);
  assert.ok(wide.x >= PDF_MARGIN_PT - 0.01);
  assert.ok(wide.w <= pageW - 2 * PDF_MARGIN_PT + 0.01);
  assert.ok(Math.abs(wide.w / wide.h - 1000 / 400) < 1e-6);

  const tall = fitImageRect(400, 1200, pageW, pageH);
  assert.ok(tall.h <= pageH - 2 * PDF_MARGIN_PT + 0.01);
  assert.ok(Math.abs(tall.w / tall.h - 400 / 1200) < 1e-6);
});

test("print SVG width is stable", () => {
  assert.equal(PRINT_SVG_WIDTH, 720);
});
