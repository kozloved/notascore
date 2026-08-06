"use client";

import { useEffect, useRef } from "react";

function gauss(x, mu, sig) {
  const d = (x - mu) / sig;
  return Math.exp(-0.5 * d * d);
}

// ECG-like single heartbeat (P–QRS–T) over t in [0, 1]. Returns a vertical
// offset roughly in [-0.3, 1] with a tall R spike near the middle.
function beat(t) {
  return (
    0.12 * gauss(t, 0.18, 0.035) +
    -0.16 * gauss(t, 0.4, 0.013) +
    1.0 * gauss(t, 0.45, 0.015) +
    -0.28 * gauss(t, 0.5, 0.017) +
    0.22 * gauss(t, 0.72, 0.05)
  );
}

export default function HeartbeatBackground({ bpm = 72 }) {
  const canvasRef = useRef(null);
  const bpmRef = useRef(bpm);
  // Keep the latest BPM readable inside the animation loop without restarting it.
  bpmRef.current = bpm;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const LINE_GAP = 46; // px between staff lines
    const WIN = 130; // px width of the heartbeat waveform
    const AMP = 26; // px vertical amplitude of the R spike

    let W = 0;
    let H = 0;
    let lines = [];
    let colors = { line: "rgba(16,20,28,0.14)", pulse: "#ea580c" };

    function readColors() {
      const cs = getComputedStyle(document.documentElement);
      colors.line = cs.getPropertyValue("--stave-line").trim() || colors.line;
      colors.pulse = cs.getPropertyValue("--accent").trim() || colors.pulse;
    }

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      lines = [];
      const count = Math.max(1, Math.floor(H / LINE_GAP));
      const top = (H - count * LINE_GAP) / 2 + LINE_GAP / 2;
      for (let i = 0; i < count; i += 1) lines.push(Math.round(top + i * LINE_GAP));

      readColors();
    }

    let activeLine = 0;
    let headX = -WIN;
    let phase = "sweeping"; // "sweeping" | "pausing"
    let pauseUntil = 0;
    let last = performance.now();
    let raf = 0;

    function pickNextLine() {
      if (lines.length <= 1) return 0;
      let idx = activeLine;
      while (idx === activeLine) idx = Math.floor(Math.random() * lines.length);
      return idx;
    }

    function drawBaseline() {
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1;
      ctx.strokeStyle = colors.line;
      for (const y of lines) {
        ctx.beginPath();
        ctx.moveTo(0, y + 0.5);
        ctx.lineTo(W, y + 0.5);
        ctx.stroke();
      }
    }

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const currentBpm = Math.max(20, bpmRef.current || 72);

      ctx.clearRect(0, 0, W, H);
      drawBaseline();

      if (phase === "pausing") {
        if (now >= pauseUntil) {
          activeLine = pickNextLine();
          headX = -WIN / 2;
          phase = "sweeping";
        }
      } else {
        headX += currentBpm * 9 * dt; // px/sec scales with BPM
        if (headX > W + WIN / 2) {
          phase = "pausing";
          const periodic = (60000 / currentBpm) * 0.35; // heartbeat-like spacing
          const randomPause = Math.random() * 500; // random short pause
          pauseUntil = now + Math.max(120, periodic) + randomPause;
        }
      }

      if (phase === "sweeping" && lines.length) {
        const y = lines[activeLine];
        const start = headX - WIN / 2;
        ctx.strokeStyle = colors.pulse;
        ctx.globalAlpha = 0.75;
        ctx.lineWidth = 1.8;
        ctx.shadowColor = colors.pulse;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        let started = false;
        const from = Math.max(0, start);
        const to = Math.min(W, start + WIN);
        for (let x = from; x <= to; x += 2) {
          const t = (x - start) / WIN;
          const yy = y - beat(t) * AMP;
          if (!started) {
            ctx.moveTo(x, yy);
            started = true;
          } else {
            ctx.lineTo(x, yy);
          }
        }
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.globalAlpha = 1;
      }

      raf = requestAnimationFrame(frame);
    }

    resize();
    window.addEventListener("resize", resize);

    const observer = new MutationObserver(readColors);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "style", "class"],
    });

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    if (reduceMotion) {
      drawBaseline();
    } else {
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      observer.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} className="heartbeat-bg" aria-hidden="true" />;
}
