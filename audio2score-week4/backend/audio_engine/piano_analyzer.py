"""Piano-specific audio analysis: velocity, sustain, pedal."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import NoteEvent


@dataclass
class PedalEvent:
    time_sec: float
    value: int
    confidence: float


@dataclass
class PianoAnalysis:
    notes: list[NoteEvent]
    pedal_events: list[PedalEvent]


class PianoAudioAnalyzer:
    """Refine piano note velocities and detect sustain pedal (CC64)."""

    def analyze(
        self, audio: NormalizedAudio, notes: list[NoteEvent]
    ) -> PianoAnalysis:
        import librosa

        y = audio.samples
        sr = audio.sample_rate
        if not notes or y.size == 0:
            return PianoAnalysis(notes=notes, pedal_events=[])

        refined: list[NoteEvent] = []
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        max_env = float(np.max(onset_env)) if onset_env.size else 1.0

        for note in notes:
            frame = librosa.time_to_frames(note.start_time, sr=sr, hop_length=512)
            frame = min(max(0, frame), len(onset_env) - 1) if onset_env.size else 0
            attack = float(onset_env[frame]) / max(max_env, 1e-8) if onset_env.size else 0.5
            vel = int(min(127, max(20, 30 + attack * 90)))
            refined.append(
                NoteEvent(
                    pitch=note.pitch,
                    start_time=note.start_time,
                    end_time=note.end_time,
                    velocity=vel,
                    confidence=note.confidence,
                )
            )

        pedal_events = self._detect_pedal(y, sr, refined)
        return PianoAnalysis(notes=refined, pedal_events=pedal_events)

    def _detect_pedal(
        self, y: np.ndarray, sr: int, notes: list[NoteEvent]
    ) -> list[PedalEvent]:
        """Heuristic: harmonic energy persists after note offsets → pedal down."""
        import librosa

        events: list[PedalEvent] = []
        if len(notes) < 2:
            return events

        rms = librosa.feature.rms(y=y, hop_length=512)[0]
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

        note_ends = sorted(n.end_time for n in notes)
        pedal_on = False
        for i, t in enumerate(times):
            if i >= len(rms):
                break
            recent_ends = [e for e in note_ends if t - 0.3 < e <= t]
            if recent_ends and rms[i] > 0.02 and not pedal_on:
                events.append(PedalEvent(time_sec=t, value=127, confidence=0.5))
                pedal_on = True
            elif pedal_on and rms[i] < 0.01:
                events.append(PedalEvent(time_sec=t, value=0, confidence=0.5))
                pedal_on = False

        return events
