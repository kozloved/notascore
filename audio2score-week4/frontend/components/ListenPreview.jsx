"use client";

import { useEffect, useRef, useState } from "react";

import {
  MidiPreviewPlayer,
  fetchArrayBuffer,
  formatClock,
} from "../lib/midiPlayback";

function PlayIcon({ playing }) {
  if (playing) {
    return (
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden="true"
      >
        <rect x="6" y="5" width="4.5" height="14" rx="1" />
        <rect x="13.5" y="5" width="4.5" height="14" rx="1" />
      </svg>
    );
  }
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M8 5.5v13l11-6.5-11-6.5z" />
    </svg>
  );
}

function TransportRow({
  label,
  hint,
  playing,
  loading,
  disabled,
  current,
  duration,
  error,
  onToggle,
  onSeek,
}) {
  const progress = duration > 0 ? Math.min(1, current / duration) : 0;

  const seekFromEvent = (event) => {
    if (disabled || duration <= 0 || !onSeek) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    onSeek(ratio * duration);
  };

  return (
    <div className={"listen-row" + (playing ? " is-playing" : "")}>
      <button
        type="button"
        className="listen-play"
        onClick={onToggle}
        disabled={disabled || loading}
        aria-label={playing ? `Stop ${label}` : `Play ${label}`}
      >
        {loading ? (
          <span className="spinner spinner-dark" aria-hidden="true" />
        ) : (
          <PlayIcon playing={playing} />
        )}
      </button>
      <div className="listen-meta">
        <div className="listen-labels">
          <strong>{label}</strong>
          <span>{hint}</span>
        </div>
        <button
          type="button"
          className="listen-bar"
          onClick={seekFromEvent}
          disabled={disabled || duration <= 0}
          aria-label={`Seek ${label}`}
        >
          <span
            className="listen-bar-fill"
            style={{ width: `${progress * 100}%` }}
          />
        </button>
        {error ? (
          <p className="listen-error">{error}</p>
        ) : (
          <p className="listen-time">
            {formatClock(current)} / {formatClock(duration)}
          </p>
        )}
      </div>
    </div>
  );
}

export default function ListenPreview({ apiUrl, jobId, filename }) {
  const isMidiSource = /\.midi?$/i.test(filename || "");
  const audioRef = useRef(null);
  const midiPlayerRef = useRef(null);
  const midiCacheRef = useRef({});
  const [active, setActive] = useState(null);
  const [loading, setLoading] = useState(null);
  const [errors, setErrors] = useState({});
  const [clocks, setClocks] = useState({
    source: { current: 0, duration: 0 },
    midi: { current: 0, duration: 0 },
    midi_score: { current: 0, duration: 0 },
  });

  const sourceUrl = `${apiUrl}/jobs/${jobId}/source`;
  const midiUrl = `${apiUrl}/jobs/${jobId}/result?format=midi`;
  const scoreUrl = `${apiUrl}/jobs/${jobId}/result?format=midi_score`;

  useEffect(() => {
    midiPlayerRef.current = new MidiPreviewPlayer();
    return () => {
      midiPlayerRef.current?.stop();
    };
  }, [jobId]);

  const setClock = (id, current, duration) => {
    setClocks((prev) => ({
      ...prev,
      [id]: {
        current,
        duration: duration ?? prev[id]?.duration ?? 0,
      },
    }));
  };

  const setError = (id, message) => {
    setErrors((prev) => ({ ...prev, [id]: message || "" }));
  };

  const pauseAudio = () => {
    const audio = audioRef.current;
    if (audio && !audio.paused) {
      audio.pause();
    }
  };

  const midiCallbacks = (id) => ({
    onTick: (current, total) => setClock(id, current, total),
    onEnd: () => {
      setActive((now) => (now === id ? null : now));
      setClock(id, 0, midiPlayerRef.current?.duration || 0);
    },
  });

  const playMidiTrack = async (id, url) => {
    pauseAudio();
    if (active === id) {
      await midiPlayerRef.current?.stop();
      setClock(id, 0, clocks[id]?.duration || 0);
      setActive(null);
      return;
    }

    setLoading(id);
    setError(id, "");
    try {
      await midiPlayerRef.current?.stop();
      if (active) {
        setClock(active, 0, clocks[active]?.duration || 0);
      }
      let buffer = midiCacheRef.current[id];
      if (!buffer) {
        buffer = await fetchArrayBuffer(url);
        midiCacheRef.current[id] = buffer;
      }
      await midiPlayerRef.current.play(buffer.slice(0), 0, midiCallbacks(id));
      setClock(id, 0, midiPlayerRef.current.duration);
      setActive(id);
    } catch (err) {
      setError(id, err?.message || "Could not play MIDI");
      setActive(null);
    } finally {
      setLoading(null);
    }
  };

  const seekMidi = async (id, url, seconds) => {
    setLoading(id);
    try {
      pauseAudio();
      if (active && active !== id) {
        await midiPlayerRef.current?.stop();
        setClock(active, 0, clocks[active]?.duration || 0);
      }
      if (active === id) {
        await midiPlayerRef.current.seek(seconds);
      } else {
        let buffer = midiCacheRef.current[id];
        if (!buffer) {
          buffer = await fetchArrayBuffer(url);
          midiCacheRef.current[id] = buffer;
        }
        await midiPlayerRef.current.play(
          buffer.slice(0),
          seconds,
          midiCallbacks(id)
        );
        setActive(id);
      }
      setClock(id, seconds, midiPlayerRef.current.duration);
    } catch (err) {
      setError(id, err?.message || "Could not seek MIDI");
    } finally {
      setLoading(null);
    }
  };

  const toggleAudio = async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (active && active !== "source") {
      await midiPlayerRef.current?.stop();
      setClock(active, 0, clocks[active]?.duration || 0);
    }
    if (!audio.paused) {
      audio.pause();
      setActive(null);
      return;
    }
    try {
      await audio.play();
      setActive("source");
      setError("source", "");
    } catch (err) {
      setError("source", err?.message || "Could not play audio");
    }
  };

  const onAudioMeta = () => {
    const audio = audioRef.current;
    if (!audio) return;
    setClock("source", audio.currentTime || 0, audio.duration || 0);
  };

  return (
    <section className="listen" aria-label="Listening previews">
      <h3 className="listen-title">Listen</h3>
      <p className="listen-lead">
        Compare the original with the raw MIDI and the quantized score MIDI.
      </p>

      {!isMidiSource && (
        <audio
          ref={audioRef}
          src={sourceUrl}
          preload="metadata"
          aria-hidden="true"
          onLoadedMetadata={onAudioMeta}
          onDurationChange={onAudioMeta}
          onTimeUpdate={() => {
            const audio = audioRef.current;
            if (!audio) return;
            setClock("source", audio.currentTime || 0, audio.duration || 0);
          }}
          onEnded={() => {
            setActive((now) => (now === "source" ? null : now));
            const audio = audioRef.current;
            setClock("source", 0, audio?.duration || 0);
          }}
          onPlay={() => setActive("source")}
          onPause={() =>
            setActive((now) => (now === "source" ? null : now))
          }
          onError={() => setError("source", "Could not load the original audio")}
        />
      )}

      {isMidiSource ? (
        <TransportRow
          label="Original"
          hint="Uploaded MIDI"
          playing={active === "source"}
          loading={loading === "source"}
          current={clocks.source.current}
          duration={clocks.source.duration}
          error={errors.source}
          onToggle={() => playMidiTrack("source", sourceUrl)}
          onSeek={(seconds) => seekMidi("source", sourceUrl, seconds)}
        />
      ) : (
        <TransportRow
          label="Original"
          hint="Uploaded audio"
          playing={active === "source"}
          loading={false}
          current={clocks.source.current}
          duration={clocks.source.duration}
          error={errors.source}
          onToggle={toggleAudio}
          onSeek={(seconds) => {
            const audio = audioRef.current;
            if (!audio) return;
            audio.currentTime = seconds;
            setClock("source", seconds, audio.duration || 0);
          }}
        />
      )}

      <TransportRow
        label="MIDI"
        hint="Raw DAW — unquantized"
        playing={active === "midi"}
        loading={loading === "midi"}
        current={clocks.midi.current}
        duration={clocks.midi.duration}
        error={errors.midi}
        onToggle={() => playMidiTrack("midi", midiUrl)}
        onSeek={(seconds) => seekMidi("midi", midiUrl, seconds)}
      />

      <TransportRow
        label="MIDI (score)"
        hint="Quantized to the sheet"
        playing={active === "midi_score"}
        loading={loading === "midi_score"}
        current={clocks.midi_score.current}
        duration={clocks.midi_score.duration}
        error={errors.midi_score}
        onToggle={() => playMidiTrack("midi_score", scoreUrl)}
        onSeek={(seconds) => seekMidi("midi_score", scoreUrl, seconds)}
      />
    </section>
  );
}
