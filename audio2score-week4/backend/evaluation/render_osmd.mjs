#!/usr/bin/env node
/**
 * Production-style OSMD preview. Uses the same constructor/engraving options
 * as frontend/components/SheetResult.jsx. Writes HTML always; SVG when
 * Playwright + Chromium are available.
 *
 * Usage:
 *   node evaluation/render_osmd.mjs <musicxml> <out_dir>
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(readFileSync(join(here, "osmd_config.json"), "utf8"));
const xmlPath = process.argv[2];
const outDir = resolve(process.argv[3] || ".");
if (!xmlPath) {
  console.error("usage: node render_osmd.mjs <musicxml> <out_dir>");
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });
const xml = readFileSync(xmlPath, "utf8");
const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>NotaScore OSMD QA</title>
  <style>
    html, body { margin: 0; background: #f7f4ee; }
    #osmd { width: 900px; margin: 16px auto; background: white; }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/opensheetmusicdisplay@2.1.1/build/opensheetmusicdisplay.min.js"></script>
</head>
<body>
  <div id="osmd"></div>
  <script>
    const xml = ${JSON.stringify(xml)};
    const config = ${JSON.stringify(config)};
    const OSMD = window.opensheetmusicdisplay.OpenSheetMusicDisplay;
    const osmd = new OSMD(document.getElementById("osmd"), config.constructor);
    if (osmd.EngravingRules) {
      for (const [key, value] of Object.entries(config.engravingRules)) {
        osmd.EngravingRules[key] = value;
      }
    }
    osmd.load(xml).then(() => {
      osmd.zoom = config.zoom;
      osmd.render();
      window.__osmdReady = true;
    });
  </script>
</body>
</html>
`;
const htmlPath = join(outDir, "osmd_preview.html");
writeFileSync(htmlPath, html);
writeFileSync(join(outDir, "osmd_config.used.json"), JSON.stringify(config, null, 2));
console.log(`wrote ${htmlPath}`);

try {
  const { chromium } = await import("playwright");
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 1400 } });
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.__osmdReady === true, null, { timeout: 30000 });
  const svg = await page.$eval("#osmd svg", (el) => el.outerHTML);
  writeFileSync(join(outDir, "osmd.svg"), svg);
  await page.screenshot({ path: join(outDir, "osmd.png"), fullPage: true });
  await browser.close();
  console.log("wrote osmd.svg and osmd.png");
} catch (err) {
  console.log(`OSMD snapshot skipped: ${err.message}`);
  process.exit(0);
}
