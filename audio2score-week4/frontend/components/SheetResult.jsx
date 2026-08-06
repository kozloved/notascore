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
          backend: "canvas",
          autoResize: true,
          drawTitle: false,
          drawPartNames: false,
        });
        osmdRef.current = osmd;

        await osmd.load(xml);
        if (cancelled) return;
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
      const canvases = containerRef.current?.querySelectorAll("canvas");
      if (!canvases || canvases.length === 0) {
        throw new Error("Sheet preview is not ready yet");
      }

      const { jsPDF } = await import("jspdf");
      let pdf = null;

      canvases.forEach((canvas, index) => {
        const w = canvas.width;
        const h = canvas.height;
        const orientation = w >= h ? "landscape" : "portrait";
        const imgData = canvas.toDataURL("image/png");

        if (index === 0) {
          pdf = new jsPDF({ orientation, unit: "pt", format: [w, h] });
        } else {
          pdf.addPage([w, h], orientation);
        }
        pdf.addImage(imgData, "PNG", 0, 0, w, h);
      });

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
        <div
          ref={containerRef}
          className="sheet-preview"
          style={{ display: previewState === "ready" ? "block" : "none" }}
        />
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
