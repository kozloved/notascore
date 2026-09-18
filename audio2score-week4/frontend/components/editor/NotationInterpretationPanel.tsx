"use client";

import { useEffect, useState } from "react";

import {
  conflictMessage,
  getNotationSettings,
  saveNotationSettings,
  type NotationSettings,
  type PolicyException,
} from "../../lib/jobs";
import Button from "../ui/Button";
import SegmentedControl from "../ui/SegmentedControl";

type NotationInterpretationPanelProps = {
  jobId: string;
  revision: number;
  timeSignature?: string;
  provenance?: string | null;
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
  onApplied,
}: NotationInterpretationPanelProps) {
  const [settings, setSettings] = useState<NotationSettings | null>(null);
  const [meter, setMeter] = useState(timeSignature || "4/4");
  const [pickup, setPickup] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [fallback, setFallback] = useState<string | null>(null);
  const [exceptions, setExceptions] = useState<PolicyException[]>([]);

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
      })
      .catch(() => {
        if (!cancelled) setStatus("Could not load notation settings.");
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, revision, timeSignature]);

  const apply = async (body: Partial<NotationSettings> & { reset?: boolean }) => {
    setBusy(true);
    setStatus("");
    try {
      const saved = await saveNotationSettings(jobId, {
        ...body,
        revision,
      });
      setSettings(saved.notation_settings);
      setMeter(saved.notation_settings.meter || timeSignature || "4/4");
      setPickup(
        saved.notation_settings.pickup_beats == null
          ? ""
          : String(saved.notation_settings.pickup_beats)
      );
      setFallback(saved.fallback || null);
      setExceptions(saved.policy_exceptions || []);
      await onApplied();
      setStatus(saved.transcribed ? "Updated." : "Score updated from the original performance.");
    } catch (err) {
      setStatus(conflictMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!settings) {
    return status ? (
      <p className="ns-editor-save" role="status">
        {status}
      </p>
    ) : null;
  }

  return (
    <section className="ns-notation-panel" aria-label="Notation interpretation">
      <div className="ns-notation-row">
        <SegmentedControl
          compact
          label="Notation interpretation"
          value={settings.interpretation}
          disabled={busy}
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
        <SegmentedControl
          compact
          label="Display grid"
          value={settings.display_grid}
          disabled={busy}
          onChange={(display_grid) =>
            void apply({
              ...settings,
              display_grid,
            })
          }
          options={[...GRID_OPTIONS]}
        />
      </div>
      <div className="ns-notation-row">
        <label className="ns-notation-field">
          Meter
          <input
            value={meter}
            onChange={(event) => setMeter(event.target.value)}
            disabled={busy}
            aria-label="Time signature"
          />
        </label>
        <label className="ns-notation-field">
          Pickup beats
          <input
            value={pickup}
            onChange={(event) => setPickup(event.target.value)}
            disabled={busy}
            inputMode="decimal"
            placeholder="0"
            aria-label="Pickup beats"
          />
        </label>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
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
          disabled={busy}
          onClick={() => void apply({ reset: true })}
        >
          Reset interpretation
        </Button>
      </div>
      <p className="ns-notation-note">
        These controls rewrite the derived score only. Original performance MIDI
        and playback stay unchanged.
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
        <p className="ns-editor-save" role="status">
          {status}
        </p>
      ) : null}
    </section>
  );
}
