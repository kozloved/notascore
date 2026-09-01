"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";

import { track } from "../../lib/analytics";

const AUDIO_SRC = "/demo/example.wav";
const SCORE_SRC = "/demo/example.musicxml";

export default function DemoPreview() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [scoreState, setScoreState] = useState<"loading" | "ready" | "error">(
    "loading"
  );
  const [audioError, setAudioError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function render() {
      try {
        const res = await fetch(SCORE_SRC);
        if (!res.ok) throw new Error("missing");
        const xml = await res.text();
        if (cancelled || !sheetRef.current) return;
        const { OpenSheetMusicDisplay } = await import("opensheetmusicdisplay");
        sheetRef.current.innerHTML = "";
        const osmd = new OpenSheetMusicDisplay(sheetRef.current, {
          backend: "svg",
          autoResize: true,
          drawTitle: false,
          drawSubtitle: false,
          drawComposer: false,
          drawCredits: false,
          drawPartNames: false,
        });
        await osmd.load(xml);
        if (cancelled) return;
        osmd.render();
        setScoreState("ready");
      } catch {
        if (!cancelled) setScoreState("error");
      }
    }
    render();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
      return;
    }
    track("demo_played");
    audio
      .play()
      .then(() => {
        setPlaying(true);
        setAudioError(false);
      })
      .catch(() => {
        setPlaying(false);
        setAudioError(true);
      });
  };

  return (
    <div className="ns-demo">
      <div className="ns-demo-col">
        <p className="ns-kicker">Original recording</p>
        <div className="ns-demo-player">
          <button
            type="button"
            className="ns-demo-play"
            onClick={toggle}
            aria-label={playing ? "Pause example recording" : "Play example recording"}
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <div className="ns-demo-meta">
            <strong>Example piano figure</strong>
            <span>
              {formatTime(progress)} / {formatTime(duration)}
            </span>
            <div
              className="listen-bar"
              role="slider"
              aria-label="Playback position"
              aria-valuemin={0}
              aria-valuemax={duration || 0}
              aria-valuenow={progress}
              tabIndex={0}
              onClick={(event) => {
                const audio = audioRef.current;
                if (!audio || !duration) return;
                const rect = event.currentTarget.getBoundingClientRect();
                const ratio = Math.min(
                  1,
                  Math.max(0, (event.clientX - rect.left) / rect.width)
                );
                audio.currentTime = ratio * duration;
              }}
            >
              <span
                className="listen-bar-fill"
                style={{
                  width: `${duration ? (progress / duration) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        </div>
        <p className="ns-demo-note">
          {audioError
            ? "The example recording couldn’t be played."
            : "Example — a short piano figure. Recording → score."}
        </p>
        <audio
          ref={audioRef}
          src={AUDIO_SRC}
          preload="metadata"
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
          onTimeUpdate={(e) => setProgress(e.currentTarget.currentTime || 0)}
          onError={() => setAudioError(true)}
          onEnded={() => {
            setPlaying(false);
            setProgress(0);
          }}
        />
      </div>

      <div className="ns-demo-flow" aria-hidden="true">
        <span>↓</span>
        <strong>NotaScore</strong>
        <span>↓</span>
      </div>

      <div className="ns-demo-col">
        <p className="ns-kicker">Sheet music</p>
        <div className="ns-demo-score">
          {scoreState !== "ready" && (
            <p className="sheet-status">
              {scoreState === "error"
                ? "The example score could not be shown."
                : "Writing the example score…"}
            </p>
          )}
          <div ref={sheetRef} className="sheet-preview" />
        </div>
      </div>
    </div>
  );
}

function formatTime(seconds: number) {
  if (!seconds || Number.isNaN(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
