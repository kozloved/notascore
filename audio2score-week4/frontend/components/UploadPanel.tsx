"use client";

import { useEffect, useRef, useState } from "react";
import { uploadAudio, type Job, type TranscriptionMode } from "../lib/api";
import { getJob } from "../lib/jobs";
import { parseMode, polyphonicAvailable } from "../lib/modes";
import SheetResult from "./SheetResult";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ACCEPTED = ".wav,.mp3,.m4a,.flac,.mid,.midi,audio/*,audio/midi";

function statusLabel(status?: string) {
  switch (status) {
    case "queued":
      return "Listening to your recording";
    case "processing":
      return "Writing your score";
    case "completed":
      return "Your score is ready";
    case "failed":
      return "We could not finish this score";
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
  const [mode, setMode] = useState<TranscriptionMode>("solo");
  const [polyAvailable, setPolyAvailable] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("notascore-mode");
      setMode(parseMode(stored));
    } catch {}
    fetch(`${API_URL}/health`)
      .then(async (response) => {
        if (!response.ok) return;
        const data = await response.json();
        setPolyAvailable(polyphonicAvailable(data));
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
  const polyBlocked = isMidiFile || !polyAvailable;
  const effectiveMode: TranscriptionMode = polyBlocked ? "solo" : mode;

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

      <div className="mb-4 grid grid-cols-2 gap-2 rounded-[10px] border border-border bg-surface p-1">
        <button
          type="button"
          onClick={() => changeMode("solo")}
          disabled={busy}
          aria-pressed={effectiveMode === "solo"}
          className={
            "rounded px-3 py-2 text-sm font-medium transition " +
            (effectiveMode === "solo"
              ? "bg-primary text-on-primary"
              : "text-secondary hover:text-foreground")
          }
        >
          Solo
          <span className="mt-0.5 block text-[0.65rem] font-normal uppercase tracking-wide opacity-80">
            Basic Pitch
          </span>
        </button>
        <button
          type="button"
          onClick={() => changeMode("polyphonic")}
          disabled={busy || polyBlocked}
          aria-pressed={effectiveMode === "polyphonic"}
          className={
            "rounded px-3 py-2 text-sm font-medium transition " +
            (effectiveMode === "polyphonic"
              ? "bg-primary text-on-primary"
              : "text-secondary hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40")
          }
        >
          Polyphonic
          <span className="mt-0.5 block text-[0.65rem] font-normal uppercase tracking-wide opacity-80">
            YourMT3
          </span>
        </button>
      </div>
      <p className="mb-5 text-xs text-muted">
        {isMidiFile
          ? "MIDI files skip note detection — the score is written from the file."
          : polyAvailable
            ? "Solo runs Basic Pitch here. Polyphonic sends audio to a YourMT3 GPU worker."
            : "Polyphonic needs a remote MT3 worker (MT3_ENDPOINT or MT3_TRANSCRIBE_COMMAND)."}
      </p>

      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <button
          type="button"
          onClick={pickFile}
          disabled={busy}
          className="min-h-12 flex-1 rounded-[10px] border border-border bg-surface px-5 py-3 text-left text-[0.95rem] text-foreground transition hover:border-foreground/30 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {file ? (
            <span className="block truncate font-medium">{file.name}</span>
          ) : (
            <span className="text-muted">Choose audio or MIDI file</span>
          )}
          <span className="mt-0.5 block text-xs text-muted">
            WAV, MP3, M4A, FLAC, or MIDI
          </span>
        </button>

        <button
          type="button"
          onClick={handleUpload}
          disabled={!file || busy}
          className="min-h-12 shrink-0 rounded-[10px] bg-primary px-7 py-3 text-sm font-medium tracking-wide text-on-primary transition hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          {phase === "uploading"
            ? "Uploading…"
            : phase === "transcribing"
              ? "Writing…"
              : "Create a score"}
        </button>
      </div>

      {(phase !== "idle" || job) && (
        <div className="mt-8 animate-[rise_0.5s_ease-out_both]">
          <div className="mb-2 flex items-baseline justify-between gap-4 text-sm">
            <span className="font-medium text-foreground">
              {phase === "uploading"
                ? "Uploading"
                : phase === "error"
                  ? "Something went wrong"
                  : statusLabel(job?.status)}
            </span>
            <span className="tabular-nums text-muted">{progress}%</span>
          </div>

          <div className="h-[3px] w-full overflow-hidden bg-foreground/10">
            <div
              className="h-full bg-accent transition-[width] duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>

          {job && phase !== "uploading" && (
            <p className="mt-3 text-sm text-muted">
              {job.status === "queued" && "Listening to your recording…"}
              {job.status === "processing" && "Finding the notes and writing your score…"}
              {job.status === "completed" && "Your score is ready. Download it below."}
              {job.status === "failed" && (job.error || "We could not finish this score")}
            </p>
          )}

          {errorMessage && phase === "error" && (
            <p className="mt-3 text-sm text-error">{errorMessage}</p>
          )}

          {job?.status === "completed" && job.result_available && (
            <div className="mt-6">
              <SheetResult
                apiUrl={API_URL}
                jobId={job.job_id}
                filename={job.filename}
              />
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
                className="mt-4 inline-flex min-h-11 items-center rounded-[10px] border border-border px-5 text-sm text-foreground transition hover:border-foreground/40"
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
