/** Shared OSMD → PNG → jsPDF export used by the sheet UI and evidence. */

export const PDF_SCALE = 2;
export const PDF_OPTIONS = { orientation: "portrait", unit: "pt", format: "a4" };
/** Half-inch margins on A4 so notation is not pinned to the page edge. */
export const PDF_MARGIN_PT = 36;
/**
 * Stable raster width independent of the on-screen container.
 * ~A4 content width at 96 CSS px (595pt − 2×36pt margins ≈ 523pt ≈ 697px).
 */
export const PRINT_SVG_WIDTH = 720;

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

export function svgContentSize(svg) {
  const vb = svg?.viewBox?.baseVal;
  const rect = svg?.getBoundingClientRect?.() || { width: 0, height: 0 };
  const width = (vb && vb.width > 0 ? vb.width : 0) || Math.ceil(rect.width) || 800;
  const height = (vb && vb.height > 0 ? vb.height : 0) || Math.ceil(rect.height) || 600;
  return { width, height };
}

export function svgMarkupFromElement(svg) {
  const { width: contentW, height: contentH } = svgContentSize(svg);
  // Normalize to a stable print width so screen zoom/container width cannot
  // stretch the PDF page differently from one viewport to another.
  const width = PRINT_SVG_WIDTH;
  const height = Math.max(1, Math.round((contentH * width) / contentW));
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  if (!clone.getAttribute("viewBox") && contentW > 0 && contentH > 0) {
    clone.setAttribute("viewBox", `0 0 ${contentW} ${contentH}`);
  }
  const xml = new XMLSerializer().serializeToString(clone);
  return { markup: xml, width, height };
}

export async function pngFromSvgElement(svg, scale = PDF_SCALE) {
  const { markup, width, height } = svgMarkupFromElement(svg);
  return pngFromSvgMarkup(markup, width, height, scale);
}

export async function pngFromSvgMarkup(markup, width, height, scale = PDF_SCALE) {
  const src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(markup);
  const img = await loadImage(src);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return { dataUrl: canvas.toDataURL("image/png"), w: canvas.width, h: canvas.height };
}

/**
 * Fit a raster into the printable A4 area without stretching.
 * Top-aligns so a short final page is not vertically inflated.
 */
export function fitImageRect(imgW, imgH, pageW, pageH, margin = PDF_MARGIN_PT) {
  const maxW = Math.max(1, pageW - 2 * margin);
  const maxH = Math.max(1, pageH - 2 * margin);
  const scale = Math.min(maxW / Math.max(imgW, 1), maxH / Math.max(imgH, 1));
  const w = imgW * scale;
  const h = imgH * scale;
  return {
    x: margin + (maxW - w) / 2,
    y: margin,
    w,
    h,
  };
}

function normalizePdfPage(page) {
  if (typeof page === "string") {
    return { dataUrl: page, w: null, h: null };
  }
  return {
    dataUrl: page.dataUrl,
    w: page.w || page.width || null,
    h: page.h || page.height || null,
  };
}

export function assembleScorePdf(pages, JsPDF) {
  if (!pages.length) {
    throw new Error("Sheet preview is not ready yet");
  }
  const pdf = new JsPDF(PDF_OPTIONS);
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  pages.forEach((raw, index) => {
    const page = normalizePdfPage(raw);
    if (index > 0) {
      pdf.addPage("a4", "portrait");
    }
    const imgW = page.w || pageW;
    const imgH = page.h || pageH;
    const { x, y, w, h } = fitImageRect(imgW, imgH, pageW, pageH);
    pdf.addImage(page.dataUrl, "PNG", x, y, w, h);
  });
  return pdf;
}

export async function downloadScorePdfFromContainer(container, filename, JsPDF, scale = PDF_SCALE) {
  const svgs = container?.querySelectorAll?.("svg");
  if (!svgs || svgs.length === 0) {
    throw new Error("Sheet preview is not ready yet");
  }
  const pngs = [];
  for (const svg of svgs) {
    pngs.push(await pngFromSvgElement(svg, scale));
  }
  const pdf = assembleScorePdf(pngs, JsPDF);
  pdf.save(filename);
  return { pages: pngs.length, pdf };
}
