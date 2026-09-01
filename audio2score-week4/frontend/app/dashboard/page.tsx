"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import AppShell from "../../components/layout/AppShell";
import ConfirmDialog from "../../components/ui/ConfirmDialog";
import Button from "../../components/ui/Button";
import ButtonLink from "../../components/ui/ButtonLink";
import SegmentedControl from "../../components/ui/SegmentedControl";
import { Display, Text } from "../../components/ui/Text";
import { useAuth } from "../../components/auth/AuthProvider";
import { track } from "../../lib/analytics";
import type { Job } from "../../lib/api";
import { deleteScore, listScores } from "../../lib/jobs";
import { chipLabel } from "../../lib/job-ux";
import {
  formatDuration,
  formatScoreDate,
  sortScores,
  titleFromFilename,
  type ScoreSort,
} from "../../lib/score-meta";
import { removeStoredScore } from "../../lib/session-jobs";

export default function DashboardPage() {
  const { user, loading: authLoading, configured } = useAuth();
  const [items, setItems] = useState<Job[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [sort, setSort] = useState<ScoreSort>("newest");
  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Job | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  const load = useCallback(async () => {
    if (!configured || !user) return;
    setLoadState("loading");
    try {
      const rows = await listScores();
      setItems(rows);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, [configured, user]);

  useEffect(() => {
    track("score_library_viewed");
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (!configured || !user) {
      setLoadState("ready");
      setItems([]);
      return;
    }
    void load();
  }, [authLoading, configured, user, load]);

  useEffect(() => {
    if (!user || loadState !== "ready") return;
    const inflight = items.some(
      (item) => item.status !== "completed" && item.status !== "failed"
    );
    if (!inflight) return;
    const timer = window.setInterval(() => {
      listScores()
        .then(setItems)
        .catch(() => {});
    }, 4000);
    return () => window.clearInterval(timer);
  }, [user, loadState, items]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? items.filter((item) => {
          const title = (item.title || titleFromFilename(item.filename)).toLowerCase();
          return title.includes(q) || (item.filename || "").toLowerCase().includes(q);
        })
      : items;
    return sortScores(filtered, sort);
  }, [items, query, sort]);

  const onDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteScore(pendingDelete.job_id);
      removeStoredScore(pendingDelete.job_id);
      setItems((cur) => cur.filter((row) => row.job_id !== pendingDelete.job_id));
      track("score_deleted");
      setPendingDelete(null);
    } catch {
      setDeleteError("We couldn’t delete this score. Please try again.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <AppShell variant="app" width="default">
      <Display as="h1">My Scores</Display>
      {configured && user ? (
        <Text className="tagline">Your music library.</Text>
      ) : configured ? (
        <Text className="tagline">Log in to see the scores saved to your account.</Text>
      ) : (
        <Text className="tagline">
          Sign-in isn’t available yet. You can still create a
          score.
        </Text>
      )}

      <div className="ns-page-cta">
        <ButtonLink href="/create">Create a score</ButtonLink>
        {configured && !user ? (
          <ButtonLink href="/login?next=/dashboard" variant="secondary">
            Log in
          </ButtonLink>
        ) : null}
      </div>

      {authLoading || (configured && user && loadState === "loading") ? (
        <ul className="ns-score-list" aria-busy="true" aria-label="Loading scores">
          {[0, 1, 2].map((key) => (
            <li key={key} className="ns-score-card ns-score-skeleton" />
          ))}
        </ul>
      ) : null}

      {configured && user && loadState === "error" ? (
        <div className="ns-library-error" role="alert">
          <p>We couldn’t load your scores.</p>
          <p>Please try again.</p>
          <Button variant="secondary" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : null}

      {configured && user && loadState === "ready" && items.length === 0 ? (
        <div className="ns-library-empty">
          <p>Your music library is empty.</p>
          <p>Create your first score from a recording.</p>
          <div className="ns-page-cta">
            <ButtonLink href="/create">Create a score</ButtonLink>
            <Link href="/examples" className="ns-text-link">
              Explore an example →
            </Link>
          </div>
        </div>
      ) : null}

      {configured && user && loadState === "ready" && items.length > 0 ? (
        <>
          <div className="ns-library-toolbar">
            <SegmentedControl
              label="Sort scores"
              compact
              value={sort}
              onChange={(value) => setSort(value as ScoreSort)}
              options={[
                { value: "newest", label: "Newest" },
                { value: "oldest", label: "Oldest" },
                { value: "name", label: "Name" },
              ]}
            />
            {items.length >= 6 ? (
              <label className="ns-library-search">
                <span className="sr-only">Search your music</span>
                <input
                  className="ns-input"
                  type="search"
                  placeholder="Search your music…"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
            ) : null}
          </div>
          {query.trim() && visible.length === 0 ? (
            <p className="ns-library-empty" role="status">
              No scores match that search.
            </p>
          ) : null}
          <ul className="ns-score-list">
            {visible.map((item) => {
              const title = item.title || titleFromFilename(item.filename);
              const failed = item.status === "failed";
              const ready = item.status === "completed";
              return (
                <li key={item.job_id} className="ns-score-card ns-score-card-rich">
                  <Link href={`/score/${item.job_id}`} className="ns-score-main">
                    <span className="ns-score-thumb" aria-hidden="true" />
                    <span className="ns-score-copy">
                      <strong>{title}</strong>
                      <span className="ns-score-meta">
                        {formatScoreDate(item.created_at)}
                        {item.duration_seconds
                          ? ` · ${formatDuration(item.duration_seconds)}`
                          : ""}
                      </span>
                    </span>
                    <span
                      className={
                        "chip" +
                        (ready ? " is-completed" : "") +
                        (failed ? " is-failed" : "")
                      }
                    >
                      {chipLabel(item.status)}
                    </span>
                  </Link>
                  <div className="ns-score-actions">
                    <Link href={`/score/${item.job_id}`}>Open</Link>
                    {ready ? (
                      <Link href={`/score/${item.job_id}#download`}>Download</Link>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => setPendingDelete(item)}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}

      {deleteError ? (
        <div className="ns-library-error" role="alert">
          <p>{deleteError}</p>
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this score?"
        body="This will remove the score and its generated files."
        confirmLabel="Delete score"
        busy={deleting}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void onDelete()}
      />
    </AppShell>
  );
}
