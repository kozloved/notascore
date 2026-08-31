"""Piano-specific audio analysis: velocity, sustain, pedal."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

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
    velocity_suggestions: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.velocity_suggestions:
            self.velocity_suggestions = [int(n.velocity) for n in self.notes]


class PianoAudioAnalyzer:
    """Infer piano velocities and sustain pedal (CC64) as analysis metadata.

    By default ``mutate_velocity=True`` so the legacy BasicPitchEngine path
    keeps rewriting note velocities. The understanding pipeline passes
    ``mutate_velocity=False``: suggestions stay on PianoAnalysis and the
    transcription note list is not rewritten.
    """

    def analyze(
        self,
        audio: NormalizedAudio,
        notes: list[NoteEvent],
        *,
        mutate_velocity: bool = True,
    ) -> PianoAnalysis:
        import librosa

        y = audio.samples
        sr = audio.sample_rate
        if not notes or y.size == 0:
            return PianoAnalysis(notes=notes, pedal_events=[])

        suggestions: list[int] = []
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        max_env = float(np.max(onset_env)) if onset_env.size else 1.0

        for note in notes:
            frame = librosa.time_to_frames(note.start_time, sr=sr, hop_length=512)
            frame = min(max(0, frame), len(onset_env) - 1) if onset_env.size else 0
            attack = float(onset_env[frame]) / max(max_env, 1e-8) if onset_env.size else 0.5
            vel = int(min(127, max(20, 30 + attack * 90)))
            suggestions.append(vel)

        if mutate_velocity:
            refined = [
                replace(note, velocity=vel) for note, vel in zip(notes, suggestions)
            ]
        else:
            refined = list(notes)

        pedal_events = self._detect_pedal(y, sr, refined)
        return PianoAnalysis(
            notes=refined,
            pedal_events=pedal_events,
            velocity_suggestions=suggestions,
        )

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
