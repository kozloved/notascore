"use client";

import { useEffect, useRef, useState } from "react";

import ListenPreview from "./ListenPreview";
import { apiFetch } from "../lib/api-client";
import { noteIdFromEvent, stampNoteIds } from "../lib/osmd-map";

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

export default function SheetResult({
  apiUrl,
  jobId,
  filename,
  onExport = undefined,
  interactive = false,
  revision = 0,
  notes = [],
  selectedNoteId = null,
  onSelectNote = undefined,
  onSelectPosition = undefined,
  onBeforeExport = undefined,
}) {
  const containerRef = useRef(null);
  const osmdRef = useRef(null);
  const [previewState, setPreviewState] = useState("loading"); // loading | ready | error
  const [busy, setBusy] = useState(null); // "musicxml" | "midi" | "midi_score" | "pdf" | null
  const [message, setMessage] = useState("");

  const stem = (filename || "score").replace(/\.[^/.]+$/, "");

  useEffect(() => {
    let cancelled = false;

    async function renderSheet() {
      setPreviewState("loading");
      setMessage("");

      try {
        const res = await apiFetch(
          `${apiUrl}/jobs/${jobId}/result?format=musicxml&rev=${revision}`
        );
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
          drawMetronomeMarks: true,
        });
        osmdRef.current = osmd;

        // Hide the music21-generated credits for a cleaner preview.
        if (osmd.EngravingRules) {
          osmd.EngravingRules.RenderComposer = false;
          osmd.EngravingRules.RenderTitle = false;
          osmd.EngravingRules.RenderSubtitle = false;
          osmd.EngravingRules.RenderLyricist = false;
          osmd.EngravingRules.MetronomeMarksDrawn = true;
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
        if (interactive) stampNoteIds(osmd, notes, selectedNoteId);
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
  }, [apiUrl, jobId, revision, interactive]);

  useEffect(() => {
    if (!interactive || previewState !== "ready" || !osmdRef.current) return;
    stampNoteIds(osmdRef.current, notes, selectedNoteId);
  }, [interactive, notes, selectedNoteId, previewState]);

  const onSheetPointer = async (event) => {
    if (!interactive) return;
    const fromDom = noteIdFromEvent(event.target);
    if (fromDom) {
      onSelectNote?.(fromDom);
      return;
    }
    const osmd = osmdRef.current;
    if (!osmd?.GraphicSheet || !onSelectPosition) return;
    try {
      const { PointF2D } = await import("opensheetmusicdisplay");
      const graphic = osmd.GraphicSheet;
      const svgPt = graphic.domToSvg(new PointF2D(event.clientX, event.clientY));
      const osmdPt = graphic.svgToOsmd(svgPt);
      const nearest = graphic.GetNearestNote?.(osmdPt, new PointF2D(1.5, 1.5));
      const nearestId = nearest
        ? nearest.getNoteheadSVGs?.()?.[0]?.getAttribute?.("data-note-id") ||
          nearest.getSVGGElement?.()?.getAttribute?.("data-note-id")
        : null;
      if (nearestId) {
        onSelectNote?.(nearestId);
        return;
      }
      const timestamp = graphic.tryGetTimestampFromPosition?.(osmdPt);
      if (!timestamp || typeof timestamp.RealValue !== "number") return;
      onSelectPosition(Math.max(0, timestamp.RealValue * 4), 0);
    } catch {
      /* click mapping is best-effort */
    }
  };

  const downloadFromApi = async (format, ext) => {
    setBusy(format);
    setMessage("");
    try {
      if (onBeforeExport) await onBeforeExport();
      const res = await apiFetch(
        `${apiUrl}/jobs/${jobId}/result?format=${format}&rev=${Date.now()}`
      );
      if (!res.ok) throw new Error(`Failed to download ${ext.toUpperCase()}`);
      const blob = await res.blob();
      triggerDownload(blob, `${stem}.${ext}`);
      onExport?.(format === "musicxml" ? "musicxml" : "midi");
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
      if (onBeforeExport) await onBeforeExport();
      if (osmdRef.current && containerRef.current) {
        const fresh = await apiFetch(
          `${apiUrl}/jobs/${jobId}/result?format=musicxml&rev=${Date.now()}`
        );
        if (fresh.ok) {
          await osmdRef.current.load(await fresh.text());
          osmdRef.current.render();
          if (interactive) stampNoteIds(osmdRef.current, notes, selectedNoteId);
        }
      }
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
      onExport?.("pdf");
    } catch (err) {
      setMessage(err?.message || "Failed to generate PDF");
    } finally {
      setBusy(null);
    }
  };

  const pdfDisabled = previewState !== "ready" || busy !== null;

  return (
    <div className={"sheet" + (interactive ? " is-editor" : "")}>
      <div className={"sheet-preview-wrap" + (interactive ? " is-editor" : "")}>
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
        <div
          ref={containerRef}
          className="sheet-preview"
          onClick={onSheetPointer}
          onKeyDown={(event) => {
            if (!interactive) return;
            if (event.key !== "Enter" && event.key !== " ") return;
            const id = noteIdFromEvent(event.target);
            if (id) {
              event.preventDefault();
              onSelectNote?.(id);
            }
          }}
        />
        {previewState === "ready" && !interactive && (
          <>
            <div className="sheet-fade" aria-hidden="true" />
            <div className="sheet-fade-strong" aria-hidden="true" />
          </>
        )}
      </div>

      <ListenPreview
        apiUrl={apiUrl}
        jobId={jobId}
        filename={filename}
        revision={revision}
      />

      <div className="formats">
        <button
          type="button"
          className="btn btn-format"
          onClick={() => downloadFromApi("midi", "mid")}
          disabled={busy !== null}
          aria-label="Download MIDI"
        >
          {busy === "midi" ? <span className="spinner spinner-dark" aria-hidden="true" /> : <FileIcon />}
          MIDI
        </button>
        <button
          type="button"
          className="btn btn-format"
          onClick={() => downloadFromApi("midi_score", "score.mid")}
          disabled={busy !== null}
          aria-label="Download MIDI that matches the score"
        >
          {busy === "midi_score" ? <span className="spinner spinner-dark" aria-hidden="true" /> : <FileIcon />}
          MIDI (score)
        </button>
        <button
          type="button"
          className="btn btn-format"
          onClick={() => downloadFromApi("musicxml", "musicxml")}
          disabled={busy !== null}
          aria-label="Download MusicXML"
        >
          {busy === "musicxml" ? <span className="spinner spinner-dark" aria-hidden="true" /> : <FileIcon />}
          MusicXML
        </button>
        <button
          type="button"
          className="btn btn-format"
          onClick={downloadPdf}
          disabled={pdfDisabled}
          aria-label="Download PDF"
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
