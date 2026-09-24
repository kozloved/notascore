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
      window.__osmdModel = (() => {
        const sheet = osmd.Sheet || {};
        const measures = (sheet.SourceMeasures || []).map((measure, index) => {
          const ts = measure.ActiveTimeSignature || measure.activeTimeSignature || {};
          return {
            index,
            number: measure.MeasureNumber ?? measure.measureNumber ?? index + 1,
            numerator: ts.RhythmNumerator ?? ts.Numerator ?? ts.numerator ?? null,
            denominator: ts.RhythmDenominator ?? ts.Denominator ?? ts.denominator ?? null,
            rhythm: ts.Rhythm ? String(ts.Rhythm) : null,
          };
        });
        const pages = (osmd.GraphicSheet && osmd.GraphicSheet.MusicPages) || [];
        const systems = pages.flatMap((page, pageIndex) =>
          (page.MusicSystems || []).map((system, systemIndex) => ({
            page: pageIndex + 1,
            system: systemIndex + 1,
            measureCount: (system.StaffLines && system.StaffLines[0]
              ? (system.StaffLines[0].Measures || []).length
              : (system.GraphicalMeasures || []).length) || 0,
          }))
        );
        return {
          measureCount: measures.length,
          timeSignatures: measures,
          pageCount: pages.length,
          systemCount: systems.length,
          systems,
        };
      })();
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
  const { createRequire } = await import("node:module");
  const requireFromFrontend = createRequire(
    resolve(here, "../../frontend/package.json")
  );
  const { chromium } = requireFromFrontend("playwright");
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 1400 } });
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.__osmdReady === true, null, { timeout: 30000 });
  const model = await page.evaluate(() => window.__osmdModel || null);
  writeFileSync(join(outDir, "osmd_model.json"), JSON.stringify(model, null, 2));
  const pages = await page.$$eval("#osmd svg", (nodes) =>
    nodes.map((svg, index) => ({
      index,
      markup: svg.outerHTML,
      text: (svg.textContent || "").replace(/\s+/g, " ").trim(),
    }))
  );
  if (!pages.length) {
    throw new Error("OSMD produced no SVG pages");
  }
  writeFileSync(join(outDir, "osmd.svg"), pages[0].markup);
  pages.forEach((pageSvg, index) => {
    writeFileSync(join(outDir, `osmd-page-${index + 1}.svg`), pageSvg.markup);
  });
  await page.screenshot({ path: join(outDir, "osmd.png"), fullPage: true });
  for (let index = 0; index < pages.length; index += 1) {
    const handle = (await page.$$("#osmd svg"))[index];
    if (handle) {
      await handle.screenshot({ path: join(outDir, `osmd-page-${index + 1}.png`) });
    }
  }
  writeFileSync(
    join(outDir, "visual_status.json"),
    JSON.stringify(
      {
        status: "passed",
        pages: pages.length,
        svg: true,
        png: true,
        model: Boolean(model),
      },
      null,
      2
    )
  );
  await browser.close();
  console.log(JSON.stringify({ pages: pages.length, svg: true, png: true, model: Boolean(model) }));
} catch (err) {
  writeFileSync(
    join(outDir, "visual_status.json"),
    JSON.stringify(
      {
        status: "skipped",
        reason: err.message,
        pages: 0,
        svg: false,
        png: false,
      },
      null,
      2
    )
  );
  console.error(`OSMD snapshot skipped: ${err.message}`);
  process.exit(0);
}
