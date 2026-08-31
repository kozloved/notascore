/** In-page MIDI playback with Tone.js (no extra soundfont download). */

import { apiFetch } from "./api-client";

const SYNTH_OPTIONS = {
  oscillator: { type: "triangle" },
  envelope: {
    attack: 0.005,
    decay: 0.28,
    sustain: 0.28,
    release: 0.55,
  },
};

export function formatClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "0:00";
  }
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export async function fetchArrayBuffer(url) {
  const response = await apiFetch(url);
  if (!response.ok) {
    throw new Error(`Could not load preview (${response.status})`);
  }
  return response.arrayBuffer();
}

export class MidiPreviewPlayer {
  constructor() {
    this._Tone = null;
    this._Midi = null;
    this._synth = null;
    this._buffer = null;
    this._duration = 0;
    this._offset = 0;
    this._startedAt = 0;
    this._raf = 0;
    this._onTick = null;
    this._onEnd = null;
  }

  get duration() {
    return this._duration;
  }

  async play(buffer, offset = 0, { onTick, onEnd } = {}) {
    await this.stop();
    if (!this._Tone || !this._Midi) {
      const [toneMod, midiMod] = await Promise.all([
        import("tone"),
        import("@tonejs/midi"),
      ]);
      this._Tone = toneMod;
      this._Midi = midiMod.Midi;
    }

    const Tone = this._Tone;
    await Tone.start();

    this._buffer = buffer;
    const parsed = new this._Midi(buffer);
    this._duration = Number(parsed.duration) || 0;
    this._offset = Math.max(0, Math.min(offset, Math.max(this._duration - 0.05, 0)));
    this._onTick = onTick || null;
    this._onEnd = onEnd || null;

    const synth = new Tone.PolySynth(Tone.Synth, SYNTH_OPTIONS);
    synth.maxPolyphony = 64;
    synth.volume.value = -8;
    synth.toDestination();
    this._synth = synth;

    const now = Tone.now() + 0.06;
    for (const track of parsed.tracks) {
      for (const note of track.notes) {
        const start = note.time - this._offset;
        if (start + note.duration <= 0) continue;
        const attack = Math.max(0, start);
        const dur = note.duration - Math.max(0, -start);
        if (dur <= 0.01) continue;
        synth.triggerAttackRelease(
          note.name,
          dur,
          now + attack,
          Math.max(0.05, Math.min(1, note.velocity || 0.7))
        );
      }
    }

    this._startedAt = performance.now();
    this._tick();
  }

  seek(seconds) {
    if (!this._buffer) return Promise.resolve();
    return this.play(this._buffer, seconds, {
      onTick: this._onTick,
      onEnd: this._onEnd,
    });
  }

  async stop() {
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = 0;
    }
    if (this._synth) {
      try {
        this._synth.releaseAll();
        this._synth.dispose();
      } catch {
        /* already gone */
      }
      this._synth = null;
    }
    this._onTick = null;
    this._onEnd = null;
    this._offset = 0;
  }

  _currentTime() {
    const elapsed = (performance.now() - this._startedAt) / 1000;
    return Math.min(this._duration, this._offset + elapsed);
  }

  _tick = () => {
    const time = this._currentTime();
    if (this._onTick) this._onTick(time, this._duration);
    if (time >= this._duration - 0.03) {
      const ended = this._onEnd;
      this.stop().then(() => {
        if (ended) ended();
      });
      return;
    }
    this._raf = requestAnimationFrame(this._tick);
  };
}
