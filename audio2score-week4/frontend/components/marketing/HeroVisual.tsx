import type { CSSProperties } from "react";

export default function HeroVisual() {
  return (
    <div className="ns-hero-visual" aria-hidden="true">
      <div className="ns-hero-panel ns-hero-wave">
        <p className="ns-hero-caption">Recording</p>
        <div className="ns-wave" role="presentation">
          {Array.from({ length: 28 }, (_, i) => (
            <span key={i} style={{ "--i": i } as CSSProperties} />
          ))}
        </div>
      </div>
      <div className="ns-hero-flow">
        <span className="ns-hero-arrow">↓</span>
        <strong>NotaScore</strong>
        <span className="ns-hero-arrow">↓</span>
      </div>
      <div className="ns-hero-panel ns-hero-score">
        <p className="ns-hero-caption">Score</p>
        <svg viewBox="0 0 280 92" className="ns-stave-svg">
          {[18, 30, 42, 54, 66].map((y) => (
            <line
              key={y}
              x1="12"
              x2="268"
              y1={y}
              y2={y}
              stroke="currentColor"
              strokeWidth="1.1"
            />
          ))}
          <path
            d="M28 18 L28 78 L34 78 L34 70 L28 70"
            fill="currentColor"
            opacity="0.85"
          />
          {[
            [70, 54],
            [108, 48],
            [146, 42],
            [184, 36],
            [222, 30],
          ].map(([x, y]) => (
            <ellipse
              key={x}
              cx={x}
              cy={y}
              rx="7"
              ry="5"
              transform={`rotate(-18 ${x} ${y})`}
              fill="currentColor"
            />
          ))}
        </svg>
      </div>
    </div>
  );
}
