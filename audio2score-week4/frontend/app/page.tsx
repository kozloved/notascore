"use client";

import { useEffect, useState } from "react";
import SheetResult from "../components/SheetResult";
import { API_URL, uploadAudio, type Job } from "../lib/api";

type Theme = "system" | "light" | "dark";

type Health = {
  status?: string;
  engine?: string;
};

const THEME_OPTIONS: {
  value: Theme;
  label: string;
  icon: React.ReactNode;
}[] = [
  {
    value: "system",
    label: "System",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <path d="M8 21h8" />
        <path d="M12 17v4" />
      </svg>
    ),
  },
  {
    value: "light",
    label: "Light",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2" />
        <path d="M12 20v2" />
        <path d="m4.9 4.9 1.4 1.4" />
        <path d="m17.7 17.7 1.4 1.4" />
        <path d="M2 12h2" />
        <path d="M20 12h2" />
        <path d="m6.3 17.7-1.4 1.4" />
        <path d="m19.1 4.9-1.4 1.4" />
      </svg>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
      </svg>
    ),
  },
];

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploadState, setUploadState] = useState<
    "idle" | "uploading" | "success" | "error"
  >("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    try {
      const stored = localStorage.getItem("notascore-theme");
      if (stored === "light" || stored === "dark" || stored === "system") {
        setTheme(stored);
      }
    } catch {
      // ignore
    }
  }, []);

  const changeTheme = (next: Theme) => {
    setTheme(next);
    try {
      localStorage.setItem("notascore-theme", next);
    } catch {
      // ignore
    }
    document.documentElement.setAttribute("data-theme", next);
  };

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then(async (response) => {
        if (response.ok) {
          setHealth(await response.json());
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      attempts += 1;

      try {
        const response = await fetch(`${API_URL}/jobs/${jobId}`);
        const data = (await response.json()) as Job;

        if (response.ok) {
          setJob(data);

          if (data.status === "completed" || data.status === "failed") {
            return;
          }
        }

        if (attempts < 120) {
          timer = setTimeout(poll, 2000);
        }
      } catch {
        if (attempts < 120) {
          timer = setTimeout(poll, 2000);
        }
      }
    };

    timer = setTimeout(poll, 1000);

    return () => {
      clearTimeout(timer);
    };
  }, [jobId]);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] || null);
  };

  const handleUpload = async () => {
    if (!file) return;

    setUploadState("uploading");
    setErrorMessage("");
    setJobId(null);
    setJob(null);

    try {
      const created = await uploadAudio(file);
      setJobId(created.job_id);
      setJob(created);
      setUploadState("success");
    } catch (error) {
      setUploadState("error");
      setErrorMessage(
        error instanceof Error ? error.message : "Upload failed"
      );
    }
  };

  const isUploading = uploadState === "uploading";
  const progress = job?.progress || 0;
  const status = job?.status || "queued";

  return (
    <main className="page">
      <div className="container">
        <div className="topbar">
          <div className="theme-toggle" role="group" aria-label="Theme">
            {THEME_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={
                  "theme-option" + (theme === opt.value ? " is-active" : "")
                }
                onClick={() => changeTheme(opt.value)}
                aria-pressed={theme === opt.value}
              >
                {opt.icon}
                <span className="label">{opt.label}</span>
              </button>
            ))}
          </div>
        </div>

        <header className="hero">
          <h1 className="wordmark">
            NotaScore
            <span className="note" aria-hidden="true">
              ♪
            </span>
          </h1>
          <p className="tagline">
            AI-powered audio to sheet music. Upload a track and receive MusicXML.
          </p>
          {health && (
            <span className="badge">
              <span className="dot" />
              API {health.status} · {health.engine} engine
            </span>
          )}
        </header>

        <section className="card">
          <input
            id="audio-file"
            className="file-input"
            type="file"
            accept=".wav,.mp3,.m4a,.flac,audio/*"
            onChange={handleFileChange}
            disabled={isUploading}
          />
          <label
            htmlFor="audio-file"
            className={
              "dropzone" +
              (file ? " has-file" : "") +
              (isUploading ? " is-disabled" : "")
            }
          >
            <svg
              className="dz-icon"
              width="26"
              height="26"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 16V4" />
              <path d="m7 9 5-5 5 5" />
              <path d="M5 20h14" />
            </svg>
            <span className="dz-title">
              {file ? file.name : "Choose an audio file"}
            </span>
            <span className="dz-sub">WAV, MP3, M4A or FLAC · up to 25 MB</span>
          </label>

          <button
            type="button"
            className="btn btn-primary"
            onClick={handleUpload}
            disabled={!file || isUploading}
          >
            {isUploading && <span className="spinner" aria-hidden="true" />}
            {isUploading ? "Uploading…" : "Upload & Transcribe"}
          </button>

          {uploadState === "success" && !job?.error && (
            <div className="alert alert-success">
              Upload successful — job queued.
            </div>
          )}

          {uploadState === "error" && (
            <div className="alert alert-error">{errorMessage}</div>
          )}

          {job && (
            <div className="status">
              <div className="status-head">
                <h2 className="status-title">Transcription</h2>
                <span
                  className={
                    "chip" +
                    (status === "completed" ? " is-completed" : "") +
                    (status === "failed" ? " is-failed" : "")
                  }
                >
                  {status}
                </span>
              </div>

              <div className="meta">
                <span>Progress</span>
                <strong>{progress}%</strong>
              </div>
              <div className="progress">
                <div
                  className="progress-fill"
                  style={{ width: `${progress}%` }}
                />
              </div>

              <p className="jobid">
                Job ID <code>{job.job_id}</code>
              </p>

              {job.error && (
                <div className="alert alert-error">{job.error}</div>
              )}

              {status === "completed" && job.result_available && (
                <SheetResult
                  apiUrl={API_URL}
                  jobId={job.job_id}
                  filename={job.filename}
                />
              )}

              <details className="raw">
                <summary>Raw job response</summary>
                <pre>{JSON.stringify(job, null, 2)}</pre>
              </details>
            </div>
          )}
        </section>

        <p className="foot">notascore.com</p>
      </div>
    </main>
  );
}
