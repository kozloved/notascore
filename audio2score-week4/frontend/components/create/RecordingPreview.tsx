"use client";

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";

import { isMidiFilename } from "../../lib/files";
import { track } from "../../lib/analytics";

function formatTime(seconds: number) {
  if (!seconds || Number.isNaN(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function RecordingPreview({
  file,
  onDuration,
}: {
  file: File;
  onDuration?: (seconds: number) => void;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const midi = isMidiFilename(file.name);

  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  useEffect(() => {
    if (midi || !url) return;
    let cancelled = false;
    const ctx = new AudioContext();
    file
      .arrayBuffer()
      .then((buffer) => ctx.decodeAudioData(buffer))
      .then((decoded) => {
        if (cancelled) return;
        drawWave(canvasRef.current, decoded);
      })
      .catch(() => {})
      .finally(() => {
        ctx.close().catch(() => {});
      });
    return () => {
      cancelled = true;
    };
  }, [file, midi, url]);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      setPlaying(false);
      return;
    }
    track("audio_preview_played");
    audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  };

  return (
    <div className="ns-preview">
      <div className="ns-preview-head">
        <p className="ns-preview-name">{file.name}</p>
        <p className="ns-preview-meta">
          {midi ? "MIDI" : "Recording"}
          {duration ? ` · ${formatTime(duration)}` : ""}
        </p>
      </div>

      {midi ? (
        <p className="ns-preview-note">
          This MIDI file will be written as a score. Listening happens for audio
          recordings.
        </p>
      ) : (
        <>
          <canvas
            ref={canvasRef}
            className="ns-wave-canvas"
            width={640}
            height={72}
            aria-hidden="true"
          />
          <div className="ns-preview-transport">
            <button
              type="button"
              className="ns-demo-play"
              onClick={toggle}
              aria-label={playing ? "Pause recording" : "Play recording"}
            >
              {playing ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <div className="ns-demo-meta">
              <span>
                {formatTime(current)} / {formatTime(duration)}
              </span>
              <div
                className="listen-bar"
                role="slider"
                tabIndex={0}
                aria-label="Playback position"
                aria-valuemin={0}
                aria-valuemax={duration || 0}
                aria-valuenow={current}
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
                onKeyDown={(event) => {
                  const audio = audioRef.current;
                  if (!audio || !duration) return;
                  if (event.key === "ArrowRight") audio.currentTime = Math.min(duration, current + 1);
                  if (event.key === "ArrowLeft") audio.currentTime = Math.max(0, current - 1);
                }}
              >
                <span
                  className="listen-bar-fill"
                  style={{ width: `${duration ? (current / duration) * 100 : 0}%` }}
                />
              </div>
            </div>
          </div>
          {url ? (
            <audio
              ref={audioRef}
              src={url}
              preload="metadata"
              onLoadedMetadata={(e) => {
                const next = e.currentTarget.duration || 0;
                setDuration(next);
                onDuration?.(next);
              }}
              onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime || 0)}
              onEnded={() => {
                setPlaying(false);
                setCurrent(0);
              }}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

function drawWave(canvas: HTMLCanvasElement | null, buffer: AudioBuffer) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const data = buffer.getChannelData(0);
  const width = canvas.width;
  const height = canvas.height;
  const step = Math.floor(data.length / width);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = getComputedStyle(canvas).color || "#101A2C";
  for (let x = 0; x < width; x += 2) {
    let max = 0;
    const start = x * step;
    for (let i = 0; i < step; i += 4) {
      max = Math.max(max, Math.abs(data[start + i] || 0));
    }
    const h = Math.max(2, max * height);
    ctx.fillRect(x, (height - h) / 2, 1.5, h);
  }
}
