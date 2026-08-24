"""Clean raw note lists before notation."""

from __future__ import annotations

from dataclasses import replace

from mir.types import NoteEvent


class MIDICleaner:
    """Merge duplicates, drop micro-notes, group chords, preserve expressivity."""

    def __init__(
        self,
        merge_threshold_sec: float = 0.025,
        min_duration_sec: float = 0.04,
        chord_window_sec: float = 0.05,
        timing_drift_sec: float = 0.015,
        octave_window_sec: float = 0.05,
        octave_keep_ratio: float = 0.6,
        drop_octave_ghosts: bool = True,
    ):
        self.merge_threshold_sec = merge_threshold_sec
        self.min_duration_sec = min_duration_sec
        self.chord_window_sec = chord_window_sec
        self.timing_drift_sec = timing_drift_sec
        self.octave_window_sec = octave_window_sec
        self.octave_keep_ratio = octave_keep_ratio
        self.drop_octave_ghosts = drop_octave_ghosts

    def clean(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        if not notes:
            return []
        notes = self._remove_micro_notes(notes)
        notes = self._merge_duplicates(notes)
        if self.drop_octave_ghosts:
            notes = self._drop_octave_ghosts(notes)
        notes = self._snap_chord_starts(notes)
        notes = self._correct_drift(notes)
        return sorted(notes, key=lambda n: (n.start_time, n.pitch))

    def _remove_micro_notes(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        return [n for n in notes if n.duration >= self.min_duration_sec]

    def _merge_duplicates(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        by_pitch: dict[int, list[NoteEvent]] = {}
        for n in notes:
            by_pitch.setdefault(n.pitch, []).append(n)

        merged: list[NoteEvent] = []
        for pitch, group in by_pitch.items():
            group.sort(key=lambda n: n.start_time)
            cur = group[0]
            for nxt in group[1:]:
                if abs(nxt.start_time - cur.start_time) <= self.merge_threshold_sec:
                    cur = NoteEvent(
                        pitch=pitch,
                        start_time=min(cur.start_time, nxt.start_time),
                        end_time=max(cur.end_time, nxt.end_time),
                        velocity=max(cur.velocity, nxt.velocity),
                        confidence=max(cur.confidence, nxt.confidence),
                    )
                else:
                    merged.append(cur)
                    cur = nxt
            merged.append(cur)
        return merged

    @staticmethod
    def _strength(note: NoteEvent) -> float:
        if 0.0 < note.confidence < 1.0:
            return float(note.confidence)
        return max(int(note.velocity), 1) / 127.0

    def _drop_octave_ghosts(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        """Drop quieter ±12/±24 copies that start with a stronger note.

        Similar-strength octaves (real doubled piano writing) are kept.
        A note is never dropped if it is the only remaining pitch covering
        its time span.
        """
        if len(notes) < 2:
            return notes

        keep = [True] * len(notes)
        order = sorted(
            range(len(notes)),
            key=lambda i: (-self._strength(notes[i]), notes[i].start_time, notes[i].pitch),
        )

        for i in order:
            if not keep[i]:
                continue
            a = notes[i]
            sa = self._strength(a)
            for j in order:
                if i == j or not keep[j]:
                    continue
                b = notes[j]
                interval = abs(int(a.pitch) - int(b.pitch))
                if interval not in (12, 24):
                    continue
                if abs(a.start_time - b.start_time) > self.octave_window_sec:
                    continue
                overlap = min(a.end_time, b.end_time) - max(a.start_time, b.start_time)
                if overlap <= 0:
                    continue
                sb = self._strength(b)
                if sa < sb:
                    continue
                if sb / max(sa, 1e-9) >= self.octave_keep_ratio:
                    continue

                still_covered = any(
                    k != j
                    and keep[k]
                    and min(notes[k].end_time, b.end_time)
                    - max(notes[k].start_time, b.start_time)
                    > 0
                    for k in range(len(notes))
                )
                if not still_covered:
                    continue
                keep[j] = False

        return [n for idx, n in enumerate(notes) if keep[idx]]

    def _snap_chord_starts(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        """Align near-simultaneous notes to a common onset (e.g. C/E/G at 0.500)."""
        if len(notes) < 2:
            return notes

        sorted_notes = sorted(notes, key=lambda n: n.start_time)
        clusters: list[list[NoteEvent]] = []
        cluster = [sorted_notes[0]]
        for n in sorted_notes[1:]:
            if n.start_time - cluster[0].start_time <= self.chord_window_sec:
                cluster.append(n)
            else:
                clusters.append(cluster)
                cluster = [n]
        clusters.append(cluster)

        result: list[NoteEvent] = []
        for cluster in clusters:
            if len(cluster) >= 2:
                anchor = min(n.start_time for n in cluster)
                for n in cluster:
                    result.append(
                        replace(n, start_time=anchor)
                    )
            else:
                result.extend(cluster)
        return result

    def _correct_drift(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        """Light grid snap without destroying rubato (only tiny nudges)."""
        corrected: list[NoteEvent] = []
        for n in notes:
            start = n.start_time
            # Snap only if within drift threshold to 1ms grid
            grid = round(start * 1000) / 1000.0
            if abs(start - grid) <= self.timing_drift_sec:
                start = grid
            corrected.append(replace(n, start_time=start))
        return corrected
