"use client";

import { useEffect, useRef, useState } from "react";

import { getJob } from "../lib/jobs";
import type { Job } from "../lib/api";
import { upsertStoredScore } from "../lib/session-jobs";

export function useJobPoll(jobId: string | null, onTerminal?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const terminal = useRef(onTerminal);
  terminal.current = onTerminal;

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let attempts = 0;

    const poll = async () => {
      attempts += 1;
      try {
        const next = await getJob(jobId);
        if (cancelled) return;
        setJob(next);
        setError("");
        upsertStoredScore({
          job_id: next.job_id,
          filename: next.filename || "Recording",
          title: next.title,
          status: next.status,
          created_at: next.created_at,
          progress: next.progress,
          source_kind: next.source_kind,
          duration_seconds: next.duration_seconds,
        });
        if (next.status === "completed" || next.status === "failed") {
          terminal.current?.(next);
          return;
        }
      } catch (err) {
        if (cancelled) return;
        if (attempts > 3) {
          setError("We couldn’t check this score right now.");
        }
      }
      if (!cancelled && attempts < 360) timer = setTimeout(poll, 2000);
    };

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return { job, error };
}
