#!/usr/bin/env node
/**
 * Production PDF export for an already-rendered OSMD preview HTML.
 *
 * Lives under frontend/ so Node resolves jspdf (and optional playwright)
 * from frontend/node_modules. Changing cwd alone does not change require
 * resolution for a script written to /tmp.
 *
 * Usage:
 *   node scripts/export-sheet-pdf.mjs <osmd_preview.html> <out.pdf>
 */
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { writeFileSync } from "node:fs";

import { assembleScorePdf, PDF_SCALE, PRINT_SVG_WIDTH } from "../lib/sheet-pdf.js";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(here, "..");

const htmlPath = process.argv[2];
const pdfPath = process.argv[3];
if (!htmlPath || !pdfPath) {
  console.error("usage: node scripts/export-sheet-pdf.mjs <osmd_preview.html> <out.pdf>");
  process.exit(2);
}

let jsPDF;
try {
  ({ jsPDF } = require("jspdf"));
} catch (err) {
  console.error(`Cannot find module jspdf from ${frontendDir}: ${err.message}`);
  process.exit(1);
}

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (err) {
  console.error(`Cannot find module playwright from ${frontendDir}: ${err.message}`);
  process.exit(1);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1000, height: 1400 } });
await page.goto(pathToFileURL(resolve(htmlPath)).href, { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__osmdReady === true, null, { timeout: 30000 });
const pages = await page.$$eval(
  "#osmd svg",
  (nodes, printWidth) =>
    nodes.map((svg) => {
      const vb = svg.viewBox?.baseVal;
      const rect = svg.getBoundingClientRect();
      const contentW = (vb && vb.width > 0 ? vb.width : 0) || Math.ceil(rect.width) || 800;
      const contentH = (vb && vb.height > 0 ? vb.height : 0) || Math.ceil(rect.height) || 600;
      const width = printWidth;
      const height = Math.max(1, Math.round((contentH * width) / contentW));
      const clone = svg.cloneNode(true);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      clone.setAttribute("width", String(width));
      clone.setAttribute("height", String(height));
      if (!clone.getAttribute("viewBox") && contentW > 0 && contentH > 0) {
        clone.setAttribute("viewBox", `0 0 ${contentW} ${contentH}`);
      }
      return {
        markup: new XMLSerializer().serializeToString(clone),
        width,
        height,
      };
    }),
  PRINT_SVG_WIDTH
);
if (!pages.length) {
  await browser.close();
  throw new Error("Sheet preview is not ready yet");
}

const pngs = [];
for (const pageSvg of pages) {
  const dataUrl = await page.evaluate(
    async ({ markup, width, height, scale }) => {
      const src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(markup);
      const img = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = src;
      });
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/png");
    },
    { ...pageSvg, scale: PDF_SCALE }
  );
  pngs.push({ dataUrl, w: Math.round(pageSvg.width * PDF_SCALE), h: Math.round(pageSvg.height * PDF_SCALE) });
}
await browser.close();

const pdf = assembleScorePdf(pngs, jsPDF);
writeFileSync(pdfPath, Buffer.from(pdf.output("arraybuffer")));
console.log(JSON.stringify({ pages: pngs.length, pdf: pdfPath }));
