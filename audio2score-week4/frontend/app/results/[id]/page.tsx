"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { resultDownloadUrl, type Job } from "../../../lib/api";
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
        setError(err instanceof Error ? err.message : "Failed to load job");
      }
    };

    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id]);

  return (
    <main className="min-h-screen bg-[#dfe7f1] px-6 py-16">
      <div className="mx-auto max-w-2xl">
        <p className="font-display text-3xl font-semibold text-ink">NotaScore</p>
        <h1 className="mt-4 font-display text-2xl text-score">
          Transcription Result
        </h1>

        {error && <p className="mt-4 text-red-700">{error}</p>}

        {job && (
          <div className="mt-6 space-y-3 text-sm text-slate">
            <p>
              <span className="font-medium text-ink">Status:</span> {job.status}
            </p>
            <p>
              <span className="font-medium text-ink">Progress:</span>{" "}
              {job.progress ?? 0}%
            </p>
            {job.error && <p className="text-red-700">{job.error}</p>}
            {job.status === "completed" && job.result_available && (
              <a
                href={resultDownloadUrl(job.job_id)}
                download
                className="mt-4 inline-flex min-h-11 items-center bg-ink px-5 text-sm font-medium text-mist transition hover:bg-score"
              >
                Download MusicXML
              </a>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
