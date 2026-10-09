"use client";

import { useEffect, useRef, useState } from "react";

import {
  conflictMessage,
  getNotationSettings,
  saveNotationSettings,
  type DetectedInterpretation,
  type NotationSettings,
  type PolicyException,
  type RhythmicFeel,
  type SourceStyle,
  type TimingFeel,
} from "../../lib/jobs";
import {
  ALGORITHM_VERSION_CURRENT,
  ALGORITHM_VERSION_READABLE_V2,
  rhythmicFeelLabel,
  type AlgorithmVersionChoice,
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

function asAlgorithmChoice(version: string | undefined): AlgorithmVersionChoice {
  return version === ALGORITHM_VERSION_READABLE_V2
    ? ALGORITHM_VERSION_READABLE_V2
    : ALGORITHM_VERSION_CURRENT;
}

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
  const [detected, setDetected] = useState<DetectedInterpretation | null>(null);
  const [swingRatio, setSwingRatio] = useState("");
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
        setDetected(payload.detected_interpretation || null);
        setSwingRatio(
          payload.notation_settings.swing_ratio == null
            ? ""
            : String(payload.notation_settings.swing_ratio)
        );
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
      setDetected(saved.detected_interpretation || null);
      setSwingRatio(
        saved.notation_settings.swing_ratio == null
          ? ""
          : String(saved.notation_settings.swing_ratio)
      );
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

  const algorithmValue = asAlgorithmChoice(settings.algorithm_version);
  const selectorDisabled = busy || !regenAvailable;

  return (
    <section className="ns-notation-panel" aria-label="Notation interpretation">
      <div className="ns-notation-row">
        <div className="ns-notation-version">
          <p className="ns-notation-control-label" id="ns-notation-version-label">
            Notation version
          </p>
          <SegmentedControl
            label="Notation version"
            value={algorithmValue}
            disabled={selectorDisabled}
            onChange={(algorithm_version: AlgorithmVersionChoice) => {
              if (algorithm_version === algorithmValue) return;
              void apply({
                ...settings,
                algorithm_version,
              });
            }}
            options={[
              {
                value: ALGORITHM_VERSION_CURRENT,
                label: "Standard",
              },
              {
                value: ALGORITHM_VERSION_READABLE_V2,
                label: "Experimental",
              },
            ]}
          />
          <p className="ns-notation-note ns-notation-version-help">
            Changes how notes and rests are written. Uses the same
            transcription. Experimental is opt-in and not claimed to be better.
          </p>
          {!regenAvailable ? (
            <p className="ns-notation-note" role="status">
              {regenReason ||
                "Notation version switching is unavailable for this score."}
            </p>
          ) : null}
        </div>
      </div>
      <div className="ns-notation-row">
        <div className="ns-notation-control">
          <p className="ns-notation-control-label">Interpretation</p>
          <SegmentedControl
            label="Notation interpretation"
            value={settings.interpretation}
            disabled={busy || !regenAvailable}
            onChange={(interpretation) =>
              void apply({
                ...settings,
                interpretation,
                algorithm_version: settings.algorithm_version,
              })
            }
            options={[
              { value: "readable", label: "Readable" },
              { value: "literal", label: "Literal" },
            ]}
          />
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
        <div className="ns-notation-control">
          <p className="ns-notation-control-label">Source style</p>
          <SegmentedControl
            label="Source style"
            value={settings.source_style || "auto"}
            disabled={busy || !regenAvailable}
            onChange={(source_style: SourceStyle) =>
              void apply({ ...settings, source_style })
            }
            options={[
              { value: "auto", label: "Auto" },
              { value: "jazz", label: "Jazz" },
              { value: "classical", label: "Classical" },
              { value: "pop_rock", label: "Pop/Rock" },
              { value: "contemporary_art", label: "Contemporary" },
            ]}
          />
        </div>
        <div className="ns-notation-control">
          <p className="ns-notation-control-label">Feel</p>
          <SegmentedControl
            label="Rhythmic feel"
            value={settings.rhythmic_feel || "auto"}
            disabled={busy || !regenAvailable}
            onChange={(rhythmic_feel: RhythmicFeel) =>
              void apply({ ...settings, rhythmic_feel })
            }
            options={[
              { value: "auto", label: "Auto" },
              { value: "straight", label: "Straight" },
              { value: "swing_eighths", label: "Swing 8ths" },
              { value: "swing_sixteenths", label: "Swing 16ths" },
              { value: "shuffle", label: "Shuffle" },
            ]}
          />
          {detected?.rhythmic_feel ? (
            <p className="ns-notation-note">
              Detected {rhythmicFeelLabel(detected.rhythmic_feel)}
              {settings.rhythmic_feel && settings.rhythmic_feel !== "auto"
                ? ". Your setting is used instead."
                : ". You can correct it here."}
            </p>
          ) : null}
        </div>
        <div className="ns-notation-control">
          <p className="ns-notation-control-label">Timing</p>
          <SegmentedControl
            label="Timing feel"
            value={settings.timing || "auto"}
            disabled={busy || !regenAvailable}
            onChange={(timing: TimingFeel) => void apply({ ...settings, timing })}
            options={[
              { value: "auto", label: "Auto" },
              { value: "steady", label: "Steady" },
              { value: "expressive", label: "Expressive" },
            ]}
          />
        </div>
      </div>
      <details className="ns-notation-advanced">
        <summary>Advanced interpretation</summary>
        <div className="ns-notation-row">
          <label className="ns-notation-field">
            Swing ratio
            <input
              value={swingRatio}
              onChange={(event) => setSwingRatio(event.target.value)}
              disabled={busy || !regenAvailable}
              inputMode="decimal"
              placeholder="auto"
              aria-label="Swing ratio override"
            />
          </label>
          <Button
            variant="secondary"
            size="sm"
            disabled={busy || !regenAvailable}
            onClick={() =>
              void apply({
                ...settings,
                swing_ratio: swingRatio.trim() === "" ? null : Number(swingRatio),
              })
            }
          >
            Apply ratio
          </Button>
        </div>
      </details>
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
        Readable writes conventional swing as even eighths plus a Swing mark;
        score playback then swings those eighths once. Literal keeps performed
        timing and still detects feel so you can correct it. Style, feel, and
        timing never re-run transcription. Original MIDI stays unchanged.
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
