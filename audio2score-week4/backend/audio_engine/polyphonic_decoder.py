"""Convert pitch activations to note events."""

from __future__ import annotations

import numpy as np

from mir.types import NoteEvent, OnsetCandidate, PitchMatrix


class PolyphonicDecoder:
    """Track notes across pitch frames with hysteresis."""

    def __init__(
        self,
        threshold: float = 0.3,
        min_duration_sec: float = 0.05,
        merge_gap_sec: float = 0.03,
    ):
        self.threshold = threshold
        self.min_duration_sec = min_duration_sec
        self.merge_gap_sec = merge_gap_sec

    def decode(
        self,
        matrix: PitchMatrix,
        onsets: list[OnsetCandidate] | None = None,
    ) -> list[NoteEvent]:
        if not matrix.times or not matrix.pitch_bins:
            return []

        n_frames = len(matrix.times)
        n_pitches = len(matrix.pitch_bins)
        activations = np.array(matrix.probabilities, dtype=float)

        notes: list[NoteEvent] = []
        active: dict[int, tuple[float, float, float]] = {}

        for fi in range(n_frames):
            t = matrix.times[fi]
            for pi in range(n_pitches):
                pitch = matrix.pitch_bins[pi]
                prob = activations[fi, pi] if fi < activations.shape[0] else 0.0

                if prob >= self.threshold:
                    if pitch in active:
                        start, _, peak = active[pitch]
                        active[pitch] = (start, t, max(peak, prob))
                    else:
                        active[pitch] = (t, t, prob)
                elif pitch in active:
                    start, end, peak = active.pop(pitch)
                    dur = end - start + (matrix.times[1] - matrix.times[0] if n_frames > 1 else 0.01)
                    if dur >= self.min_duration_sec:
                        vel = int(min(127, max(1, 40 + peak * 80)))
                        notes.append(
                            NoteEvent(
                                pitch=pitch,
                                start_time=start,
                                end_time=start + dur,
                                velocity=vel,
                                confidence=peak,
                            )
                        )

        frame_dt = matrix.times[1] - matrix.times[0] if n_frames > 1 else 0.01
        for pitch, (start, end, peak) in active.items():
            dur = end - start + frame_dt
            if dur >= self.min_duration_sec:
                vel = int(min(127, max(1, 40 + peak * 80)))
                notes.append(
                    NoteEvent(
                        pitch=pitch,
                        start_time=start,
                        end_time=start + dur,
                        velocity=vel,
                        confidence=peak,
                    )
                )

        notes = self._merge_repeated(notes)
        if onsets:
            notes = self._align_to_onsets(notes, onsets)
        return sorted(notes, key=lambda n: (n.start_time, n.pitch))

    def _merge_repeated(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        if not notes:
            return notes
        merged: list[NoteEvent] = []
        by_pitch: dict[int, list[NoteEvent]] = {}
        for n in notes:
            by_pitch.setdefault(n.pitch, []).append(n)

        for pitch, group in by_pitch.items():
            group.sort(key=lambda n: n.start_time)
            cur = group[0]
            for nxt in group[1:]:
                if nxt.start_time - cur.end_time <= self.merge_gap_sec:
                    cur = NoteEvent(
                        pitch=pitch,
                        start_time=cur.start_time,
                        end_time=max(cur.end_time, nxt.end_time),
                        velocity=max(cur.velocity, nxt.velocity),
                        confidence=max(cur.confidence, nxt.confidence),
                    )
                else:
                    merged.append(cur)
                    cur = nxt
            merged.append(cur)
        return merged

    def _align_to_onsets(
        self, notes: list[NoteEvent], onsets: list[OnsetCandidate]
    ) -> list[NoteEvent]:
        if not onsets:
            return notes
        onset_times = sorted(o.timestamp for o in onsets)
        aligned: list[NoteEvent] = []
        for note in notes:
            nearest = min(onset_times, key=lambda t: abs(t - note.start_time))
            if abs(nearest - note.start_time) < 0.08:
                note = NoteEvent(
                    pitch=note.pitch,
                    start_time=nearest,
                    end_time=note.end_time + (nearest - note.start_time),
                    velocity=note.velocity,
                    confidence=note.confidence,
                )
            aligned.append(note)
        return aligned
