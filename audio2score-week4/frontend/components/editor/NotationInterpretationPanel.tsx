"use client";

import { useEffect, useRef, useState } from "react";

import {
  conflictMessage,
  getNotationSettings,
  saveNotationSettings,
  type NotationSettings,
  type PolicyException,
} from "../../lib/jobs";
import {
  needsCurrentReadableEngine,
  patchForCurrentReadable,
  patchForInterpretation,
} from "../../lib/notation-style";
import Button from "../ui/Button";
import SegmentedControl from "../ui/SegmentedControl";

type NotationInterpretationPanelProps = {
  jobId: string;
  revision: number;
  timeSignature?: string;
  provenance?: string | null;
  dirty?: boolean;
  flushSave?: () => Promise<{ revision: number } | null | undefined>;
  onApplied: () => Promise<void> | void;
};

const GRID_OPTIONS = [
  { value: "auto", label: "Auto" },
  { value: "eighth", label: "⅛" },
  { value: "sixteenth", label: "16" },
  { value: "thirty-second", label: "32" },
] as const;

export default function NotationInterpretationPanel({
  jobId,
  revision,
  timeSignature,
  provenance,
  dirty = false,
  flushSave,
  onApplied,
}: NotationInterpretationPanelProps) {
  const [settings, setSettings] = useState<NotationSettings | null>(null);
  const [meter, setMeter] = useState(timeSignature || "4/4");
  const [pickup, setPickup] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [fallback, setFallback] = useState<string | null>(null);
  const [exceptions, setExceptions] = useState<PolicyException[]>([]);
  const [regenAvailable, setRegenAvailable] = useState(true);
  const [regenReason, setRegenReason] = useState<string | null>(null);
  const requestGen = useRef(0);
  const revisionRef = useRef(revision);
  revisionRef.current = revision;

  useEffect(() => {
    let cancelled = false;
    getNotationSettings(jobId)
      .then((payload) => {
        if (cancelled) return;
        setSettings(payload.notation_settings);
        setMeter(payload.notation_settings.meter || timeSignature || "4/4");
        setPickup(
          payload.notation_settings.pickup_beats == null
            ? ""
            : String(payload.notation_settings.pickup_beats)
        );
        setFallback(payload.fallback || null);
        setExceptions(payload.policy_exceptions || []);
        setRegenAvailable(payload.regeneration_available !== false);
        setRegenReason(payload.regeneration_unavailable_reason || null);
      })
      .catch(() => {
        if (!cancelled) setStatus("Could not load notation settings.");
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, revision, timeSignature]);

  const apply = async (body: Partial<NotationSettings> & { reset?: boolean }) => {
    const gen = ++requestGen.current;
    const prior = settings;
    setBusy(true);
    setStatus("Updating notation…");
    try {
      let baseRevision = revisionRef.current;
      if (dirty && flushSave) {
        const flushed = await flushSave();
        if (gen !== requestGen.current) return;
        if (flushed?.revision != null) {
          baseRevision = flushed.revision;
          revisionRef.current = flushed.revision;
        }
      }
      const saved = await saveNotationSettings(jobId, {
        ...body,
        revision: baseRevision,
      });
      if (gen !== requestGen.current) return;
      setSettings(saved.notation_settings);
      setMeter(saved.notation_settings.meter || timeSignature || "4/4");
      setPickup(
        saved.notation_settings.pickup_beats == null
          ? ""
          : String(saved.notation_settings.pickup_beats)
      );
      setFallback(saved.fallback || null);
      setExceptions(saved.policy_exceptions || []);
      if (saved.edit_revision != null) {
        revisionRef.current = saved.edit_revision;
      }
      setRegenAvailable(saved.regeneration_available !== false);
      setRegenReason(saved.regeneration_unavailable_reason || null);
      await onApplied();
      if (gen !== requestGen.current) return;
      setStatus(
        saved.transcribed
          ? "Updated."
          : "Score updated from the original performance."
      );
    } catch (err) {
      if (gen !== requestGen.current) return;
      if (prior) setSettings(prior);
      setStatus(conflictMessage(err));
    } finally {
      if (gen === requestGen.current) setBusy(false);
    }
  };

  if (!settings) {
    return status ? (
      <p className="ns-editor-save" role="status">
        {status}
      </p>
    ) : null;
  }

  const selectorDisabled = busy || !regenAvailable;

  return (
    <section className="ns-notation-panel" aria-label="Notation interpretation">
      <div className="ns-notation-row">
        <div className="ns-notation-control">
          <p className="ns-notation-control-label">Interpretation</p>
          <SegmentedControl
            label="Notation interpretation"
            value={settings.interpretation}
            disabled={selectorDisabled}
            onChange={(interpretation: "literal" | "readable") => {
              if (interpretation === settings.interpretation) return;
              void apply({
                ...settings,
                ...patchForInterpretation(interpretation),
              });
            }}
            options={[
              { value: "readable", label: "Readable" },
              { value: "literal", label: "Literal" },
            ]}
          />
          <p className="ns-notation-note">
            Readable infers conventional written rhythm from the performance.
            Literal keeps performed onsets and releases as closely as notation
            allows. Changing this regenerates the derived score.
          </p>
          {needsCurrentReadableEngine(settings) ? (
            <p className="ns-notation-note">
              This score uses a saved Readable engine. Apply the current
              Readable interpretation to regenerate it. Manual edits are kept.
              <button
                type="button"
                className="ns-text-link"
                disabled={selectorDisabled}
                onClick={() =>
                  void apply({
                    ...settings,
                    ...patchForCurrentReadable(),
                  })
                }
              >
                Apply current Readable
              </button>
            </p>
          ) : null}
          {!regenAvailable ? (
            <p className="ns-notation-note" role="status">
              {regenReason ||
                "Interpretation switching is unavailable for this score."}
            </p>
          ) : null}
        </div>
        <div className="ns-notation-control">
          <p className="ns-notation-control-label">Display grid</p>
          <SegmentedControl
            label="Display grid"
            value={settings.display_grid}
            disabled={busy || !regenAvailable}
            onChange={(display_grid) =>
              void apply({
                ...settings,
                display_grid,
              })
            }
            options={[...GRID_OPTIONS]}
          />
        </div>
        <div className="ns-notation-control">
          <p className="ns-notation-control-label">Printed tempo</p>
          <SegmentedControl
            label="Printed tempo detail"
            value={settings.printed_tempo_detail || "expressive"}
            disabled={busy || !regenAvailable}
            onChange={(printed_tempo_detail) =>
              void apply({
                ...settings,
                printed_tempo_detail,
              })
            }
            options={[
              { value: "expressive", label: "Expressive" },
              { value: "opening", label: "Opening" },
              { value: "off", label: "Off" },
            ]}
          />
          <p className="ns-notation-note">
            Playback keeps the full tempo curve. Expressive prints sustained
            changes and rit./a tempo; Opening prints only the first metronome.
          </p>
        </div>
      </div>
      <div className="ns-notation-row">
        <label className="ns-notation-field">
          Meter
          <input
            value={meter}
            onChange={(event) => setMeter(event.target.value)}
            disabled={busy || !regenAvailable}
            aria-label="Time signature"
          />
        </label>
        <label className="ns-notation-field">
          Pickup beats
          <input
            value={pickup}
            onChange={(event) => setPickup(event.target.value)}
            disabled={busy || !regenAvailable}
            inputMode="decimal"
            placeholder="0"
            aria-label="Pickup beats"
          />
        </label>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy || !regenAvailable}
          onClick={() =>
            void apply({
              ...settings,
              meter: meter.trim() || null,
              pickup_beats: pickup.trim() === "" ? null : Number(pickup),
            })
          }
        >
          Apply meter
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy || !regenAvailable}
          onClick={() => void apply({ reset: true })}
        >
          Reset interpretation
        </Button>
      </div>
      <p className="ns-notation-note">
        These controls rewrite the derived score only. Original performance MIDI
        stays byte-identical. Score playback follows the written interpretation.
        {provenance ? ` ${provenance}` : ""}
      </p>
      {fallback ? (
        <p className="ns-notation-note" role="status">
          This score is using a recovered tempo map.
        </p>
      ) : null}
      {exceptions.length ? (
        <ul className="ns-notation-note" aria-label="Notation exceptions">
          {exceptions.map((row, index) => (
            <li key={`${row.kind || "exception"}-${index}`}>
              {row.user_message ||
                row.reason ||
                "A local notation exception was required."}
            </li>
          ))}
        </ul>
      ) : null}
      {status ? (
        <p className="ns-editor-save" role="status" aria-live="polite">
          {status}
          {!busy &&
          status !== "Updating notation…" &&
          !status.startsWith("Score updated") &&
          status !== "Updated." ? (
            <button
              type="button"
              className="ns-text-link"
              onClick={() =>
                void apply({
                  ...settings,
                  algorithm_version: settings.algorithm_version,
                })
              }
            >
              Retry
            </button>
          ) : null}
        </p>
      ) : null}
    </section>
  );
}
