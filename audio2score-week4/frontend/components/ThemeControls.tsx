"use client";

type Theme = "system" | "light" | "dark";

const THEME_OPTIONS: {
  value: Theme;
  label: string;
  icon: React.ReactNode;
}[] = [
  {
    value: "system",
    label: "System",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <path d="M8 21h8" />
        <path d="M12 17v4" />
      </svg>
    ),
  },
  {
    value: "light",
    label: "Light",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2" />
        <path d="M12 20v2" />
        <path d="m4.9 4.9 1.4 1.4" />
        <path d="m17.7 17.7 1.4 1.4" />
        <path d="M2 12h2" />
        <path d="M20 12h2" />
        <path d="m6.3 17.7-1.4 1.4" />
        <path d="m19.1 4.9-1.4 1.4" />
      </svg>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
      </svg>
    ),
  },
];

export default function ThemeControls({
  theme,
  bpm,
  onThemeChange,
  onBpmChange,
}: {
  theme: Theme;
  bpm: number;
  onThemeChange: (theme: Theme) => void;
  onBpmChange: (bpm: number) => void;
}) {
  return (
    <div className="topbar">
      <div className="bpm">
        <label htmlFor="bpm-slider" className="bpm-label">
          BPM
        </label>
        <input
          id="bpm-slider"
          className="bpm-slider"
          type="range"
          min={40}
          max={200}
          value={bpm}
          onChange={(event) => onBpmChange(Number(event.target.value))}
          aria-label="Background heartbeat BPM"
        />
        <span className="bpm-value">{bpm}</span>
      </div>
      <div className="theme-toggle" role="group" aria-label="Theme">
        {THEME_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={
              "theme-option" + (theme === opt.value ? " is-active" : "")
            }
            onClick={() => onThemeChange(opt.value)}
            aria-pressed={theme === opt.value}
          >
            {opt.icon}
            <span className="label">{opt.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export type { Theme };
