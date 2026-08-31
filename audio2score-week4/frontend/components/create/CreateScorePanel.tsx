"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Upload } from "lucide-react";

import { track } from "../../lib/analytics";
import { uploadAudio } from "../../lib/api";
import {
  friendlyUploadError,
  validateRecording,
} from "../../lib/files";
import { polyphonicAvailable } from "../../lib/modes";
import {
  getActiveJobId,
  setActiveJobId,
  upsertStoredScore,
} from "../../lib/session-jobs";
import { useAuth } from "../auth/AuthProvider";
import { useJobPoll } from "../../hooks/useJobPoll";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import Card from "../ui/Card";
import SheetResult from "../SheetResult";
import ProcessingStatus from "./ProcessingStatus";
import RecordingPreview from "./RecordingPreview";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function CreateScorePanel() {
  const { user, configured } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const urlJob = params.get("job");
  const submitting = useRef(false);

  const [health, setHealth] = useState<unknown>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [uploadPercent, setUploadPercent] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [wantEnsemble, setWantEnsemble] = useState(false);

  const { job, error: pollError } = useJobPoll(jobId, (next) => {
    if (next.status === "completed") track("job_completed");
    if (next.status === "failed") track("job_failed");
  });

  useEffect(() => {
    track("create_page_viewed");
    fetch(`${API_URL}/health`)
      .then(async (response) => {
        if (response.ok) setHealth(await response.json());
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (urlJob) {
      setJobId(urlJob);
      return;
    }
    const stored = getActiveJobId();
    if (stored) setJobId(stored);
  }, [urlJob]);

  const opened = useRef(false);

  useEffect(() => {
    if (job?.status === "completed" && job.result_available && !opened.current) {
      opened.current = true;
      track("score_opened");
    }
  }, [job]);

  const polyAvailable = polyphonicAvailable(health);
  const phase =
    uploading
      ? "uploading"
      : job
        ? job.status
        : file
          ? "preview"
          : "idle";

  const takeFile = (next: File | null) => {
    if (!next) return;
    const check = validateRecording(next);
    if (check.ok === false) {
      setFile(null);
      setFileError(
        check.reason === "size"
          ? "This recording is too large. Please choose a file under 25 MB."
          : "This file can’t be transcribed. Please choose a supported audio recording."
      );
      return;
    }
    setFileError("");
    setSubmitError("");
    setFile(next);
    setJobId(null);
    setActiveJobId(null);
    router.replace("/create");
  };

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setDragging(false);
    takeFile(event.dataTransfer.files?.[0] || null);
  };

  const startJob = async () => {
    if (!file || submitting.current || uploading) return;
    submitting.current = true;
    setUploading(true);
    setUploadPercent(0);
    setSubmitError("");
    track("upload_started");
    track("score_creation_started");
    track("create_score_clicked");

    try {
      const created = await uploadAudio(
        file,
        (percent) => setUploadPercent(percent),
        wantEnsemble && polyAvailable ? "polyphonic" : "solo"
      );
      track("upload_completed");
      track("job_processing_started");
      setJobId(created.job_id);
      setActiveJobId(created.job_id);
      upsertStoredScore({
        job_id: created.job_id,
        filename: created.filename || file.name,
        status: created.status,
        created_at: created.created_at,
        progress: created.progress,
        source_kind: created.source_kind,
      });
      router.replace(`/create?job=${created.job_id}`);
    } catch (error) {
      setSubmitError(friendlyUploadError(error));
    } finally {
      setUploading(false);
      submitting.current = false;
    }
  };

  const resetToIdle = () => {
    setFile(null);
    setFileError("");
    setSubmitError("");
    setJobId(null);
    setActiveJobId(null);
    setUploadPercent(null);
    router.replace("/create");
  };

  const retry = () => {
    track("retry_started");
    setSubmitError("");
    if (file) {
      setJobId(null);
      startJob();
      return;
    }
    resetToIdle();
  };

  const ready = job?.status === "completed" && job.result_available;
  const failed = job?.status === "failed";
  const processing = Boolean(
    job && job.status !== "completed" && job.status !== "failed"
  );

  return (
    <Card id="create" className="ns-create">
      {phase === "idle" || (fileError && !file && !job) ? (
        <>
          <input
            id="audio-file"
            className="file-input"
            type="file"
            accept=".wav,.mp3,.m4a,.flac,.mid,.midi,audio/*,audio/midi"
            onChange={(event) => takeFile(event.target.files?.[0] || null)}
          />
          <label
            htmlFor="audio-file"
            className={"dropzone" + (dragging ? " is-over" : "")}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <Upload className="dz-icon" size={26} strokeWidth={1.7} aria-hidden="true" />
            <span className="dz-title">
              {dragging ? "Drop your recording" : "Drop your recording here"}
            </span>
            <span className="dz-sub">or browse files · MP3 · WAV · M4A · FLAC</span>
          </label>
          {fileError ? (
            <Alert tone="error">
              {fileError}
              <div style={{ marginTop: 8 }}>
                <Button variant="secondary" size="sm" onClick={() => setFileError("")}>
                  Choose another file
                </Button>
              </div>
            </Alert>
          ) : null}
        </>
      ) : null}

      {file && !job && !uploading ? (
        <>
          <RecordingPreview file={file} />
          {polyAvailable ? (
            <details
              className="ns-advanced"
              open={advancedOpen}
              onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}
            >
              <summary>Advanced options</summary>
              <label className="ns-advanced-row">
                <input
                  type="checkbox"
                  checked={wantEnsemble}
                  onChange={(e) => setWantEnsemble(e.target.checked)}
                />
                Several parts at once
              </label>
              <p className="mode-hint">
                Leave this off to let NotaScore choose. Use it only for piano or
                overlapping parts.
              </p>
            </details>
          ) : null}
          <Button
            onClick={startJob}
            disabled={submitting.current}
            loading={uploading}
          >
            Create your score
          </Button>
          <Button variant="ghost" onClick={resetToIdle}>
            Choose another recording
          </Button>
        </>
      ) : null}

      {uploading ? (
        <div className="ns-upload-progress" aria-live="polite">
          <p>Uploading recording…</p>
          {uploadPercent !== null ? (
            <>
              <div className="progress" role="progressbar" aria-valuenow={uploadPercent} aria-valuemin={0} aria-valuemax={100}>
                <div className="progress-fill" style={{ width: `${uploadPercent}%` }} />
              </div>
              <span className="ns-text-metadata">{uploadPercent}%</span>
            </>
          ) : (
            <p className="mode-hint">Sending your recording…</p>
          )}
          <Button disabled loading>
            Creating your score…
          </Button>
        </div>
      ) : null}

      {submitError ? <Alert tone="error">{submitError}</Alert> : null}
      {pollError && processing ? <Alert tone="error">{pollError}</Alert> : null}

      {processing ? (
        <>
          <ProcessingStatus status={job?.status} progress={job?.progress} />
          <p className="mode-hint">
            You can leave this page. NotaScore keeps working, and My Scores will
            show progress on this device.
          </p>
        </>
      ) : null}

      {failed ? (
        <div className="ns-fail" role="alert">
          <h2>We couldn’t create your score.</h2>
          <p>Something went wrong while processing your recording.</p>
          <div className="ns-page-cta">
            <Button onClick={retry} disabled={submitting.current}>
              Try again
            </Button>
            <Button variant="secondary" onClick={resetToIdle}>
              Choose another recording
            </Button>
          </div>
        </div>
      ) : null}

      {ready && job ? (
        <div className="ns-result">
          <div className="ns-result-head">
            <Link href="/dashboard" className="ns-text-link">
              ← My Scores
            </Link>
            <h2 className="ns-result-title">{job.filename || "Your score"}</h2>
            <p className="ns-preview-meta">Your score is ready.</p>
          </div>
          <SheetResult
            apiUrl={API_URL}
            jobId={job.job_id}
            filename={job.filename}
            onExport={(format) => {
              if (format === "pdf") track("export_pdf");
              else if (format === "musicxml") track("export_musicxml");
              else track("export_midi");
            }}
          />
          {!user ? (
            <div className="ns-save-panel">
              <p>
                {configured
                  ? "Create a free account to keep this score with you."
                  : "Sign-in is not configured on this workspace yet. You can still download your score."}
              </p>
              {configured ? (
                <Link
                  href={`/signup?next=/results/${job.job_id}`}
                  className="ns-btn ns-btn-secondary"
                  onClick={() => track("auth_interruption")}
                >
                  Save your score
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
