import type { CSSProperties } from "react";

import { STAGES, currentStage, headlineForJob, stageIndex } from "../../lib/job-ux";

export default function ProcessingStatus({
  status,
  progress,
}: {
  status?: string | null;
  progress?: number | null;
}) {
  const active = currentStage(status, progress);
  const activeIdx = stageIndex(active);
  const done = status === "completed";

  return (
    <div className="ns-process" aria-live="polite">
      <h2 className="ns-process-title">{headlineForJob(status, progress)}</h2>
      <ol className="ns-process-stages">
        {STAGES.map((stage, index) => {
          const state =
            done || index < activeIdx ? "done" : index === activeIdx ? "current" : "todo";
          return (
            <li key={stage.id} className={"ns-process-stage is-" + state}>
              <span className="ns-process-mark" aria-hidden="true">
                {state === "done" ? "✓" : state === "current" ? "●" : "○"}
              </span>
              {stage.label}
            </li>
          );
        })}
      </ol>
      <div className="ns-process-visual" aria-hidden="true">
        <div className="ns-wave ns-process-wave">
          {Array.from({ length: 18 }, (_, i) => (
            <span key={i} style={{ "--i": i } as CSSProperties} />
          ))}
        </div>
        <span className="ns-hero-arrow">↓</span>
        <div className="ns-hero-panel ns-hero-score ns-process-score">
          <svg viewBox="0 0 220 56" className="ns-stave-svg">
            {[10, 20, 30, 40, 50].map((y) => (
              <line
                key={y}
                x1="8"
                x2="212"
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeWidth="1"
              />
            ))}
          </svg>
        </div>
      </div>
    </div>
  );
}
