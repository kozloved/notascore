"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import AppShell from "../../components/layout/AppShell";
import ButtonLink from "../../components/ui/ButtonLink";
import { Display, Text } from "../../components/ui/Text";
import { getJob } from "../../lib/jobs";
import { chipLabel } from "../../lib/job-ux";
import {
  listStoredScores,
  removeStoredScore,
  storedTitle,
  type StoredScore,
} from "../../lib/session-jobs";

export default function DashboardPage() {
  const [items, setItems] = useState<StoredScore[]>([]);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      const stored = listStoredScores();
      const next: StoredScore[] = [];
      for (const item of stored) {
        if (item.status === "completed" || item.status === "failed") {
          next.push(item);
          continue;
        }
        try {
          const job = await getJob(item.job_id);
          next.push({
            ...item,
            status: job.status,
            progress: job.progress,
            filename: job.filename || item.filename,
          });
        } catch {
          next.push(item);
        }
      }
      if (!cancelled) setItems(next);
    };
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <AppShell variant="app" width="default">
      <Display as="h1">My Scores</Display>
      <Text className="tagline">
        Scores on this device. Account-linked history needs the service to store
        who created each job — that is not available yet.
      </Text>
      <div className="ns-page-cta">
        <ButtonLink href="/create">Create a score</ButtonLink>
      </div>
      {items.length === 0 ? (
        <p className="ns-empty">No scores on this device yet.</p>
      ) : (
        <ul className="ns-score-list">
          {items.map((item) => (
            <li key={item.job_id} className="ns-score-card">
              <Link href={`/create?job=${item.job_id}`}>
                <strong>{storedTitle(item)}</strong>
                <span
                  className={
                    "chip" +
                    (item.status === "completed" ? " is-completed" : "") +
                    (item.status === "failed" ? " is-failed" : "")
                  }
                >
                  {chipLabel(item.status)}
                </span>
              </Link>
              <button
                type="button"
                className="ns-text-link"
                onClick={() => {
                  removeStoredScore(item.job_id);
                  setItems((cur) => cur.filter((row) => row.job_id !== item.job_id));
                }}
              >
                Remove from this device
              </button>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
