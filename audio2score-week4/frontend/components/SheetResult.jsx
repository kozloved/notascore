"use client";

import { useEffect, useRef, useState } from "react";

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

async function svgToPng(svg, scale) {
  const rect = svg.getBoundingClientRect();
  const width = Math.ceil(rect.width) || svg.viewBox?.baseVal?.width || 800;
  const height = Math.ceil(rect.height) || svg.viewBox?.baseVal?.height || 600;

  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));

  const xml = new XMLSerializer().serializeToString(clone);
  const src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
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

export default function SheetResult({ apiUrl, jobId, filename }) {
  const containerRef = useRef(null);
  const osmdRef = useRef(null);
  const [previewState, setPreviewState] = useState("loading"); // loading | ready | error
  const [busy, setBusy] = useState(null); // "musicxml" | "midi" | "pdf" | null
  const [message, setMessage] = useState("");

  const stem = (filename || "score").replace(/\.[^/.]+$/, "");

  useEffect(() => {
    let cancelled = false;

    async function renderSheet() {
      setPreviewState("loading");
      setMessage("");

      try {
        const res = await fetch(`${apiUrl}/jobs/${jobId}/result?format=musicxml`);
        if (!res.ok) throw new Error("Could not load the score");
        const xml = await res.text();
        if (cancelled) return;

        const { OpenSheetMusicDisplay } = await import("opensheetmusicdisplay");
        if (cancelled || !containerRef.current) return;

        containerRef.current.innerHTML = "";
        const osmd = new OpenSheetMusicDisplay(containerRef.current, {
          backend: "svg",
          autoResize: true,
          drawTitle: false,
          drawPartNames: false,
        });
        osmdRef.current = osmd;

        // Hide the music21-generated credits for a cleaner preview.
        if (osmd.EngravingRules) {
          osmd.EngravingRules.RenderComposer = false;
          osmd.EngravingRules.RenderTitle = false;
          osmd.EngravingRules.RenderSubtitle = false;
          osmd.EngravingRules.RenderLyricist = false;
        }

        await osmd.load(xml);
        if (cancelled) return;
        // Engrave onto a portrait A4 page so the preview and PDF use real page
        // geometry instead of a tightly cropped image of the notes.
        osmd.setPageFormat("A4_P");
        // Slightly smaller engraving so the A4 top third shown in the preview
        // holds a few systems (which the progressive blur then acts on).
        osmd.zoom = 0.75;
        osmd.render();
        setPreviewState("ready");
      } catch (err) {
        if (!cancelled) {
          setPreviewState("error");
          setMessage(err?.message || "Could not render the sheet preview");
        }
      }
    }

    renderSheet();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, jobId]);

  const downloadFromApi = async (format, ext) => {
    setBusy(format);
    setMessage("");
    try {
      const res = await fetch(`${apiUrl}/jobs/${jobId}/result?format=${format}`);
      if (!res.ok) throw new Error(`Failed to download ${ext.toUpperCase()}`);
      const blob = await res.blob();
      triggerDownload(blob, `${stem}.${ext}`);
    } catch (err) {
      setMessage(err?.message || `Failed to download ${ext.toUpperCase()}`);
    } finally {
      setBusy(null);
    }
  };

  const downloadPdf = async () => {
    setBusy("pdf");
    setMessage("");
    try {
      const svgs = containerRef.current?.querySelectorAll("svg");
      if (!svgs || svgs.length === 0) {
        throw new Error("Sheet preview is not ready yet");
      }

      const { jsPDF } = await import("jspdf");
      const pdf = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });
      const pageW = pdf.internal.pageSize.getWidth();
      const pageH = pdf.internal.pageSize.getHeight();

      for (let index = 0; index < svgs.length; index += 1) {
        const { dataUrl } = await svgToPng(svgs[index], 2);
        if (index > 0) {
          pdf.addPage("a4", "portrait");
        }
        // Each OSMD page is already A4-proportioned, so it fills the page.
        pdf.addImage(dataUrl, "PNG", 0, 0, pageW, pageH);
      }

      pdf.save(`${stem}.pdf`);
    } catch (err) {
      setMessage(err?.message || "Failed to generate PDF");
    } finally {
      setBusy(null);
    }
  };

  const pdfDisabled = previewState !== "ready" || busy !== null;

  return (
    <div className="sheet">
      <div className="sheet-preview-wrap">
        {previewState === "loading" && (
          <div className="sheet-status">
            <span className="spinner spinner-dark" aria-hidden="true" />
            Rendering sheet preview…
          </div>
        )}
        {previewState === "error" && (
          <div className="sheet-status sheet-status-error">
            {message || "Could not render the sheet preview."}
          </div>
        )}
        {/* Kept mounted and visible so OpenSheetMusicDisplay always has a
            non-zero width to lay out against. */}
        <div ref={containerRef} className="sheet-preview" />
        {previewState === "ready" && (
          <>
            <div className="sheet-fade" aria-hidden="true" />
            <div className="sheet-fade-strong" aria-hidden="true" />
          </>
        )}
      </div>

      <div className="formats">
        <button
          type="button"
          className="btn btn-format"
          onClick={() => downloadFromApi("midi", "mid")}
          disabled={busy !== null}
        >
          {busy === "midi" ? <span className="spinner spinner-dark" aria-hidden="true" /> : <FileIcon />}
          MIDI
        </button>
        <button
          type="button"
          className="btn btn-format"
          onClick={() => downloadFromApi("musicxml", "musicxml")}
          disabled={busy !== null}
        >
          {busy === "musicxml" ? <span className="spinner spinner-dark" aria-hidden="true" /> : <FileIcon />}
          MusicXML
        </button>
        <button
          type="button"
          className="btn btn-format"
          onClick={downloadPdf}
          disabled={pdfDisabled}
          title={previewState !== "ready" ? "Preview must finish rendering first" : undefined}
        >
          {busy === "pdf" ? <span className="spinner spinner-dark" aria-hidden="true" /> : <FileIcon />}
          PDF
        </button>
      </div>

      {message && previewState === "ready" && (
        <p className="sheet-message">{message}</p>
      )}
    </div>
  );
}

function FileIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 15V3" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 21h14" />
    </svg>
  );
}
