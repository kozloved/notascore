"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import AppShell from "../../../components/layout/AppShell";
import Button from "../../../components/ui/Button";
import ConfirmDialog from "../../../components/ui/ConfirmDialog";
import ProcessingStatus from "../../../components/create/ProcessingStatus";
import EditableTitle from "../../../components/scores/EditableTitle";
import SheetResult from "../../../components/SheetResult";
import { Text } from "../../../components/ui/Text";
import { API_URL } from "../../../lib/api";
import { track } from "../../../lib/analytics";
import { deleteScore, retryJob } from "../../../lib/jobs";
import { useJobPoll } from "../../../hooks/useJobPoll";
import { formatDuration, titleFromFilename } from "../../../lib/score-meta";
import { removeStoredScore, setActiveJobId } from "../../../lib/session-jobs";

export default function ScorePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id || null;
  const { job, error } = useJobPoll(id, (next) => {
    if (next.status === "completed") track("job_completed");
    if (next.status === "failed") track("job_failed");
  });
  const [title, setTitle] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (id) setActiveJobId(id);
    if (job?.status === "completed") track("score_opened");
  }, [id, job?.status]);

  useEffect(() => {
    if (job?.title) setTitle(job.title);
    else if (job?.filename) setTitle(titleFromFilename(job.filename));
  }, [job?.title, job?.filename]);

  const ready = job?.status === "completed" && job.result_available;
  const failed = job?.status === "failed";
  const processing = Boolean(job && !ready && !failed);
  const notFound = Boolean(id && error && !job);

  const onDelete = async () => {
    if (!id) return;
    setDeleting(true);
    try {
      await deleteScore(id);
      removeStoredScore(id);
      track("score_deleted");
      router.replace("/dashboard");
    } catch {
      setDeleting(false);
      setConfirm(false);
    }
  };

  const onRetry = async () => {
    if (!id) return;
    setRetrying(true);
    track("retry_started");
    try {
      await retryJob(id);
    } catch {
      /* poll will surface state */
    } finally {
      setRetrying(false);
    }
  };

  return (
    <AppShell variant="app" width="default">
      <Link href="/dashboard" className="ns-text-link">
        ← My Scores
      </Link>
      {notFound ? (
        <>
          <h1 className="ns-result-title">Score not found</h1>
          <Text className="tagline">
            This score isn’t available. It may have been removed, or you may need
            to log in.
          </Text>
        </>
      ) : (
        <>
          <div className="ns-result-head">
            {id && title ? (
              <EditableTitle id={id} title={title} onSaved={setTitle} />
            ) : (
              <h1 className="ns-result-title">{title || "Your score"}</h1>
            )}
            <p className="ns-preview-meta">
              {job?.duration_seconds
                ? formatDuration(job.duration_seconds)
                : job?.filename || ""}
            </p>
          </div>

          {processing ? (
            <ProcessingStatus status={job?.status} progress={job?.progress} />
          ) : null}
          {failed ? (
            <div className="ns-fail" role="alert">
              <h2>We couldn’t create your score.</h2>
              <p>Something went wrong while processing your recording.</p>
              <div className="ns-page-cta">
                <Button onClick={() => void onRetry()} loading={retrying}>
                  Try again
                </Button>
                <Button variant="secondary" onClick={() => setConfirm(true)}>
                  Remove
                </Button>
              </div>
            </div>
          ) : null}
          {ready && job ? (
            <div id="download">
              <SheetResult
                apiUrl={API_URL}
                jobId={job.job_id}
                filename={job.filename}
                onExport={(format) => {
                  track("score_downloaded");
                  if (format === "pdf") track("export_pdf");
                  else if (format === "musicxml") track("export_musicxml");
                  else track("export_midi");
                }}
              />
              <div className="ns-page-cta">
                <Button variant="ghost" onClick={() => setConfirm(true)}>
                  Delete score
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={confirm}
        title="Delete this score?"
        body="This will remove the score and its generated files."
        confirmLabel="Delete score"
        busy={deleting}
        onCancel={() => setConfirm(false)}
        onConfirm={() => void onDelete()}
      />
    </AppShell>
  );
}
