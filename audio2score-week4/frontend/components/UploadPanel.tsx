"use client";

import { useEffect, useRef, useState } from "react";
import { resultDownloadUrl, uploadAudio, type Job, type TranscriptionMode } from "../lib/api";
import { getJob } from "../lib/jobs";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ACCEPTED = ".wav,.mp3,.m4a,.flac,.mid,.midi,audio/*,audio/midi";

function statusLabel(status?: string) {
  switch (status) {
    case "queued":
      return "Queued";
    case "processing":
      return "Transcribing";
    case "completed":
      return "Complete";
    case "failed":
      return "Failed";
    default:
      return status || "Waiting";
  }
}

export default function UploadPanel() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [phase, setPhase] = useState<
    "idle" | "uploading" | "transcribing" | "done" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [mode, setMode] = useState<TranscriptionMode>("fast");
  const [qualityAvailable, setQualityAvailable] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("notascore-mode");
      if (stored === "fast" || stored === "quality") {
        setMode(stored);
      }
    } catch {}
    fetch(`${API_URL}/health`)
      .then(async (response) => {
        if (!response.ok) return;
        const data = await response.json();
        setQualityAvailable(Boolean(data?.quality?.available));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!job?.job_id) return;
    if (job.status === "completed" || job.status === "failed") return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const next = await getJob(job.job_id);
        if (cancelled) return;
        setJob(next);

        if (next.status === "completed") {
          setPhase("done");
          return;
        }
        if (next.status === "failed") {
          setPhase("error");
          setErrorMessage(next.error || "Transcription failed");
          return;
        }

        setPhase("transcribing");
        timer = setTimeout(poll, 2000);
      } catch (error) {
        if (cancelled) return;
        timer = setTimeout(poll, 2000);
      }
    };

    timer = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [job?.job_id, job?.status]);

  const pickFile = () => inputRef.current?.click();

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] || null;
    setFile(next);
    setErrorMessage("");
    if (phase === "done" || phase === "error") {
      setPhase("idle");
      setJob(null);
      setUploadPercent(0);
    }
  };

  const isMidiFile = Boolean(file && /\.midi?$/i.test(file.name));
  const qualityBlocked = isMidiFile || !qualityAvailable;
  const effectiveMode: TranscriptionMode = qualityBlocked ? "fast" : mode;

  const changeMode = (next: TranscriptionMode) => {
    setMode(next);
    try {
      localStorage.setItem("notascore-mode", next);
    } catch {}
  };

  const handleUpload = async () => {
    if (!file || phase === "uploading" || phase === "transcribing") return;

    setPhase("uploading");
    setUploadPercent(0);
    setErrorMessage("");
    setJob(null);

    try {
      const created = await uploadAudio(file, setUploadPercent, effectiveMode);
      setJob(created);
      setPhase("transcribing");
    } catch (error) {
      setPhase("error");
      setErrorMessage(
        error instanceof Error ? error.message : "Upload failed"
      );
    }
  };

  const progress =
    phase === "uploading"
      ? uploadPercent
      : phase === "transcribing"
        ? Math.max(job?.progress ?? 5, 5)
        : phase === "done"
          ? 100
          : 0;

  const busy = phase === "uploading" || phase === "transcribing";

  return (
    <div className="w-full max-w-xl animate-[rise_0.8s_ease-out_0.15s_both]">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        className="sr-only"
        onChange={onFileChange}
        disabled={busy}
      />

      <div className="mb-4 grid grid-cols-2 gap-2 rounded-md border border-ink/15 bg-white/40 p-1">
        <button
          type="button"
          onClick={() => changeMode("fast")}
          disabled={busy}
          aria-pressed={effectiveMode === "fast"}
          className={
            "rounded px-3 py-2 text-sm font-medium transition " +
            (effectiveMode === "fast"
              ? "bg-ink text-mist"
              : "text-slate hover:text-ink")
          }
        >
          Fast
          <span className="mt-0.5 block text-[0.65rem] font-normal uppercase tracking-wide opacity-80">
            Basic Pitch
          </span>
        </button>
        <button
          type="button"
          onClick={() => changeMode("quality")}
          disabled={busy || qualityBlocked}
          aria-pressed={effectiveMode === "quality"}
          className={
            "rounded px-3 py-2 text-sm font-medium transition " +
            (effectiveMode === "quality"
              ? "bg-ink text-mist"
              : "text-slate hover:text-ink disabled:cursor-not-allowed disabled:opacity-40")
          }
        >
          Quality
          <span className="mt-0.5 block text-[0.65rem] font-normal uppercase tracking-wide opacity-80">
            MR-MT3
          </span>
        </button>
      </div>
      <p className="mb-5 text-xs text-slate">
        {isMidiFile
          ? "MIDI files skip note detection — the score is written from the file."
          : qualityAvailable
            ? "Fast runs Basic Pitch here. Quality sends audio to an MR-MT3 GPU worker."
            : "Quality needs a remote MT3 worker (MT3_ENDPOINT or MT3_TRANSCRIBE_COMMAND)."}
      </p>

      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <button
          type="button"
          onClick={pickFile}
          disabled={busy}
          className="min-h-12 flex-1 border border-ink/15 bg-white/55 px-5 py-3 text-left text-[0.95rem] text-ink backdrop-blur-sm transition hover:border-ink/30 hover:bg-white/75 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {file ? (
            <span className="block truncate font-medium">{file.name}</span>
          ) : (
            <span className="text-slate">Choose audio or MIDI file</span>
          )}
          <span className="mt-0.5 block text-xs text-slate">
            WAV, MP3, M4A, FLAC, or MIDI
          </span>
        </button>

        <button
          type="button"
          onClick={handleUpload}
          disabled={!file || busy}
          className="min-h-12 shrink-0 bg-ink px-7 py-3 text-sm font-medium tracking-wide text-mist transition hover:bg-score disabled:cursor-not-allowed disabled:bg-ink/35"
        >
          {phase === "uploading"
            ? "Uploading…"
            : phase === "transcribing"
              ? "Working…"
              : "Transcribe"}
        </button>
      </div>

      {(phase !== "idle" || job) && (
        <div className="mt-8 animate-[rise_0.5s_ease-out_both]">
          <div className="mb-2 flex items-baseline justify-between gap-4 text-sm">
            <span className="font-medium text-ink">
              {phase === "uploading"
                ? "Uploading"
                : phase === "error"
                  ? "Something went wrong"
                  : statusLabel(job?.status)}
            </span>
            <span className="tabular-nums text-slate">{progress}%</span>
          </div>

          <div className="h-[3px] w-full overflow-hidden bg-ink/10">
            <div
              className="h-full bg-brass transition-[width] duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>

          {job && phase !== "uploading" && (
            <p className="mt-3 text-sm text-slate">
              {job.status === "queued" && "Waiting in the transcription queue…"}
              {job.status === "processing" &&
                "NotaScore Transcription Engine is converting your audio…"}
              {job.status === "completed" &&
                "Ready. Download your editable score below."}
              {job.status === "failed" && (job.error || "Transcription failed")}
            </p>
          )}

          {errorMessage && phase === "error" && (
            <p className="mt-3 text-sm text-red-700">{errorMessage}</p>
          )}

          {job?.status === "completed" && job.result_available && (
            <div className="mt-6 flex flex-wrap gap-3">
              <a
                href={resultDownloadUrl(job.job_id)}
                download
                className="inline-flex min-h-11 items-center bg-ink px-5 text-sm font-medium text-mist transition hover:bg-score"
              >
                Download MusicXML
              </a>
              <button
                type="button"
                onClick={() => {
                  setFile(null);
                  setJob(null);
                  setPhase("idle");
                  setUploadPercent(0);
                  setErrorMessage("");
                  if (inputRef.current) inputRef.current.value = "";
                }}
                className="inline-flex min-h-11 items-center border border-ink/20 px-5 text-sm text-ink transition hover:border-ink/40"
              >
                New upload
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
