"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import AppShell from "../../../components/layout/AppShell";
import Alert from "../../../components/ui/Alert";
import { Display, Text } from "../../../components/ui/Text";
import SheetResult from "../../../components/SheetResult";
import { API_URL, type Job } from "../../../lib/api";
import { getJob } from "../../../lib/jobs";

export default function ResultPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const load = async () => {
      try {
        const next = await getJob(id);
        if (cancelled) return;
        setJob(next);
        setError("");

        if (next.status !== "completed" && next.status !== "failed") {
          timer = setTimeout(load, 2000);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load score");
      }
    };

    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id]);

  return (
    <AppShell variant="app" width="default">
      <Display>Your score</Display>
      <Text className="tagline">Review the notation, listen back, and download what you need.</Text>

      {error && <Alert tone="error">{error}</Alert>}

      {job && (
        <div className="status" style={{ marginTop: 24, paddingTop: 0, borderTop: "none" }}>
          <div className="status-head">
            <h2 className="status-title">
              {job.status === "completed" ? "Your score is ready" : job.status}
            </h2>
            <span
              className={
                "chip" +
                (job.status === "completed" ? " is-completed" : "") +
                (job.status === "failed" ? " is-failed" : "")
              }
            >
              {job.status}
            </span>
          </div>
          <div className="meta">
            <span>Progress</span>
            <strong>{job.progress ?? 0}%</strong>
          </div>
          {job.error && <Alert tone="error">{job.error}</Alert>}
          {job.status === "completed" && job.result_available && (
            <SheetResult
              apiUrl={API_URL}
              jobId={job.job_id}
              filename={job.filename}
            />
          )}
        </div>
      )}
    </AppShell>
  );
}
