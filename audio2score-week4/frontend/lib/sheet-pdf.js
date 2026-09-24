/** Shared OSMD → PNG → jsPDF export used by the sheet UI and evidence. */

export const PDF_SCALE = 2;
export const PDF_OPTIONS = { orientation: "portrait", unit: "pt", format: "a4" };

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

export function svgMarkupFromElement(svg) {
  const rect = svg.getBoundingClientRect?.() || { width: 0, height: 0 };
  const width = Math.ceil(rect.width) || svg.viewBox?.baseVal?.width || 800;
  const height = Math.ceil(rect.height) || svg.viewBox?.baseVal?.height || 600;
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
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

export function assembleScorePdf(pngDataUrls, JsPDF) {
  if (!pngDataUrls.length) {
    throw new Error("Sheet preview is not ready yet");
  }
  const pdf = new JsPDF(PDF_OPTIONS);
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  pngDataUrls.forEach((dataUrl, index) => {
    if (index > 0) {
      pdf.addPage("a4", "portrait");
    }
    pdf.addImage(dataUrl, "PNG", 0, 0, pageW, pageH);
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
    pngs.push((await pngFromSvgElement(svg, scale)).dataUrl);
  }
  const pdf = assembleScorePdf(pngs, JsPDF);
  pdf.save(filename);
  return { pages: pngs.length, pdf };
}
