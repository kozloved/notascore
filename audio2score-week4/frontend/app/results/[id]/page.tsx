"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import AppShell from "../../../components/layout/AppShell";
import Alert from "../../../components/ui/Alert";
import ProcessingStatus from "../../../components/create/ProcessingStatus";
import SheetResult from "../../../components/SheetResult";
import { Display, Text } from "../../../components/ui/Text";
import { API_URL } from "../../../lib/api";
import { track } from "../../../lib/analytics";
import { useJobPoll } from "../../../hooks/useJobPoll";
import { setActiveJobId } from "../../../lib/session-jobs";

export default function ResultPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id || null;
  const { job, error } = useJobPoll(id, (next) => {
    if (next.status === "completed") track("job_completed");
    if (next.status === "failed") track("job_failed");
  });

  useEffect(() => {
    if (id) setActiveJobId(id);
    if (job?.status === "completed") track("score_opened");
  }, [id, job?.status]);

  const ready = job?.status === "completed" && job.result_available;
  const failed = job?.status === "failed";
  const processing = Boolean(job && !ready && !failed);

  return (
    <AppShell variant="app" width="default">
      <Link href="/dashboard" className="ns-text-link">
        ← My Scores
      </Link>
      <Display as="h1">{job?.filename || "Your score"}</Display>
      <Text className="tagline">
        Review the notation, listen back, and download what you need.
      </Text>

      {error && <Alert tone="error">{error}</Alert>}
      {processing ? <ProcessingStatus status={job?.status} progress={job?.progress} /> : null}
      {failed ? (
        <Alert tone="error">
          We couldn’t create your score. Something went wrong while processing your
          recording.
        </Alert>
      ) : null}
      {ready && job ? (
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
      ) : null}
    </AppShell>
  );
}
