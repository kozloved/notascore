"use client";

import { useEffect, useState } from "react";
import { Upload } from "lucide-react";

import AppShell from "../components/layout/AppShell";
import Alert from "../components/ui/Alert";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import SegmentedControl from "../components/ui/SegmentedControl";
import { Display, Text } from "../components/ui/Text";
import SheetResult from "../components/SheetResult";
import { parseMode, polyphonicAvailable } from "../lib/modes";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function processingCopy(status, progress) {
  if (status === "queued") return "Listening to your recording";
  if (status === "processing" && progress < 40) return "Finding the notes";
  if (status === "processing" && progress < 75) return "Understanding the rhythm";
  if (status === "processing") return "Writing your score";
  if (status === "completed") return "Your score is ready";
  if (status === "failed") return "We could not finish this score";
  return "Preparing";
}

export default function Home() {
  const [health, setHealth] = useState(null);
  const [file, setFile] = useState(null);
  const [uploadState, setUploadState] = useState("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [mode, setMode] = useState("solo");

  useEffect(() => {
    try {
      setMode(parseMode(localStorage.getItem("notascore-mode")));
    } catch {}
  }, []);

  const changeMode = (next) => {
    setMode(next);
    try {
      localStorage.setItem("notascore-mode", next);
    } catch {}
  };

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then(async (response) => {
        if (response.ok) setHealth(await response.json());
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let attempts = 0;
    let timer;

    const poll = async () => {
      attempts += 1;
      try {
        const response = await fetch(`${API_URL}/jobs/${jobId}`);
        const data = await response.json();
        if (response.ok) {
          setJob(data);
          if (data.status === "completed" || data.status === "failed") return;
        }
        if (attempts < 360) timer = setTimeout(poll, 2000);
      } catch {
        if (attempts < 360) timer = setTimeout(poll, 2000);
      }
    };

    timer = setTimeout(poll, 1000);
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  const handleFileChange = (event) => {
    setFile(event.target.files[0]);
  };

  const isMidiFile = Boolean(file && /\.midi?$/i.test(file.name));
  const polyAvailable = polyphonicAvailable(health);
  const polyBlocked = isMidiFile || !polyAvailable;
  const effectiveMode = polyBlocked ? "solo" : mode;

  const handleUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("mode", effectiveMode);

    setUploadState("uploading");
    setErrorMessage("");
    setJobId(null);
    setJob(null);

    try {
      const response = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });
      const raw = await response.text();
      let data;
      try {
        data = JSON.parse(raw);
      } catch {
        throw new Error(
          response.ok
            ? "The service returned an unexpected response."
            : `Upload failed (${response.status})`
        );
      }
      if (!response.ok) {
        const detail = data?.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail.map((d) => d?.msg || String(d)).join("; ")
              : "Upload failed"
        );
      }
      setJobId(data.job_id);
      setJob(data);
      setUploadState("success");
    } catch (error) {
      setUploadState("error");
      setErrorMessage(error.message);
    }
  };

  const isUploading = uploadState === "uploading";
  const progress = job?.progress || 0;
  const status = job?.status || "queued";

  return (
    <AppShell variant="public" width="default">
      <header className="hero">
        <p className="hero-kicker">NotaScore</p>
        <Display>Turn your music into a score.</Display>
        <Text className="tagline" size="body-large">
          From recordings to editable sheet music in minutes.
        </Text>
        {health && (
          <span className="badge">
            <span className="dot" />
            Ready to create a score
            {polyAvailable ? " · ensemble available" : ""}
          </span>
        )}
      </header>

      <section className="how" id="how-it-works">
        <div className="how-step">
          <span className="how-index">01</span>
          <Text tone="primary">Bring a recording</Text>
          <Text size="body-small" tone="muted">
            Upload audio or MIDI. Keep the performance as you played it.
          </Text>
        </div>
        <div className="how-step">
          <span className="how-index">02</span>
          <Text tone="primary">We write the score</Text>
          <Text size="body-small" tone="muted">
            Notes, rhythm, and layout — without asking you to speak in studio jargon.
          </Text>
        </div>
        <div className="how-step">
          <span className="how-index">03</span>
          <Text tone="primary">Review and take it with you</Text>
          <Text size="body-small" tone="muted">
            Listen back, then download PDF, MIDI, or MusicXML.
          </Text>
        </div>
      </section>

      <Card id="create">
        <input
          id="audio-file"
          className="file-input"
          type="file"
          accept=".wav,.mp3,.m4a,.flac,.mid,.midi,audio/*,audio/midi"
          onChange={handleFileChange}
          disabled={isUploading}
        />
        <label
          htmlFor="audio-file"
          className={
            "dropzone" + (file ? " has-file" : "") + (isUploading ? " is-disabled" : "")
          }
        >
          <Upload className="dz-icon" size={26} strokeWidth={1.7} aria-hidden="true" />
          <span className="dz-title">
            {file ? file.name : "Choose an audio or MIDI file"}
          </span>
          <span className="dz-sub">WAV, MP3, M4A, FLAC or MIDI · up to 25 MB</span>
        </label>

        <div className="mode-block">
          <SegmentedControl
            label="Score type"
            value={effectiveMode}
            onChange={changeMode}
            disabled={isUploading}
            options={[
              { value: "solo", label: "Solo", description: "One instrument" },
              {
                value: "polyphonic",
                label: "Ensemble",
                description: "Piano & polyphony",
                disabled: polyBlocked,
              },
            ]}
          />
          <p className="mode-hint">
            {isMidiFile
              ? "MIDI files skip listening — the score is written from the file."
              : polyAvailable
                ? "Solo is for a single line. Ensemble is for piano and several parts at once."
                : "Ensemble transcription is offline on this workspace. Solo is ready."}
          </p>
        </div>

        <Button
          className="btn"
          onClick={handleUpload}
          disabled={!file || isUploading}
          loading={isUploading}
        >
          {isUploading ? "Uploading…" : "Create a score"}
        </Button>

        {uploadState === "success" && !job?.error && (
          <Alert tone="success">Upload received — we are preparing your score.</Alert>
        )}
        {uploadState === "error" && <Alert tone="error">{errorMessage}</Alert>}

        {job && (
          <div className="status">
            <div className="status-head">
              <h2 className="status-title">{processingCopy(status, progress)}</h2>
              <span
                className={
                  "chip" +
                  (status === "completed" ? " is-completed" : "") +
                  (status === "failed" ? " is-failed" : "")
                }
              >
                {status === "completed"
                  ? "Ready"
                  : status === "processing"
                    ? "Writing"
                    : status}
              </span>
            </div>

            <div className="meta">
              <span>Progress</span>
              <strong>{progress}%</strong>
            </div>
            <div className="progress">
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>

            {job.error && <Alert tone="error">{job.error}</Alert>}

            {status === "completed" && job.result_available && (
              <SheetResult
                apiUrl={API_URL}
                jobId={job.job_id}
                filename={job.filename}
              />
            )}
          </div>
        )}
      </Card>
    </AppShell>
  );
}
