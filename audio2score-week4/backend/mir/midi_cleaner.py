"""Clean raw note lists before notation.

Destructive edits are classified KEEP / SUPPRESS / UNCERTAIN with a reason.
Octave doubling is kept by default; octave ghosts are flagged, not auto-deleted.
"""

from __future__ import annotations

from dataclasses import replace

from mir.models import CleaningAction, CleaningDecision
from mir.types import NoteEvent


class MIDICleaner:
    """Merge duplicates, drop quiet micro-notes, group chords, preserve expressivity."""

    def __init__(
        self,
        merge_threshold_sec: float = 0.025,
        min_duration_sec: float = 0.04,
        chord_window_sec: float = 0.05,
        timing_drift_sec: float = 0.015,
        quiet_velocity: int = 42,
        low_confidence: float = 0.45,
        preserve_uncertain: bool = True,
        suppress_octave_ghosts: bool = False,
        octave_window_sec: float = 0.04,
        octave_duration_ratio: float = 0.55,
        octave_velocity_ratio: float = 0.38,
        shadow_mode: bool = False,
    ):
        self.merge_threshold_sec = merge_threshold_sec
        self.min_duration_sec = min_duration_sec
        self.chord_window_sec = chord_window_sec
        self.timing_drift_sec = timing_drift_sec
        self.quiet_velocity = quiet_velocity
        self.low_confidence = low_confidence
        self.preserve_uncertain = preserve_uncertain
        self.suppress_octave_ghosts = suppress_octave_ghosts
        self.octave_window_sec = octave_window_sec
        self.octave_duration_ratio = octave_duration_ratio
        self.octave_velocity_ratio = octave_velocity_ratio
        self.shadow_mode = shadow_mode

    def clean(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        cleaned, _ = self.clean_with_report(notes)
        return cleaned

    def clean_with_report(
        self, notes: list[NoteEvent]
    ) -> tuple[list[NoteEvent], list[CleaningDecision]]:
        if not notes:
            return [], []

        tagged = [n.ensure_ids(i) for i, n in enumerate(notes)]
        decisions: list[CleaningDecision] = []

        for n in tagged:
            action, reason, evidence = self._classify_micro(n)
            decisions.append(
                CleaningDecision(
                    note_id=n.note_id,
                    pitch=n.pitch,
                    start_time=n.start_time,
                    action=action,
                    reason=reason,
                    evidence=evidence,
                )
            )

        kept = [n for n in tagged if self._should_keep(n, decisions)]

        kept, merge_decisions = self._merge_duplicates(kept)
        decisions.extend(merge_decisions)
        kept = self._snap_chord_starts(kept)
        kept = self._correct_drift(kept)
        octave_decisions = self._classify_octaves(kept)
        decisions.extend(octave_decisions)
        if self.suppress_octave_ghosts and not self.shadow_mode:
            suppress_ids = {
                d.note_id
                for d in octave_decisions
                if d.action == CleaningAction.SUPPRESS
            }
            kept = [n for n in kept if n.note_id not in suppress_ids]
        return sorted(kept, key=lambda n: (n.start_time, n.pitch)), decisions

    def _should_keep(
        self, note: NoteEvent, decisions: list[CleaningDecision]
    ) -> bool:
        if self.shadow_mode:
            return True
        matching = [d for d in decisions if d.note_id == note.note_id]
        if not matching:
            return True
        action = matching[-1].action
        if action == CleaningAction.SUPPRESS:
            return False
        if action == CleaningAction.UNCERTAIN and not self.preserve_uncertain:
            return False
        return True

    def _classify_micro(
        self, note: NoteEvent
    ) -> tuple[CleaningAction, str, dict]:
        if note.duration >= self.min_duration_sec:
            return CleaningAction.KEEP, "duration_ok", {"duration": note.duration}
        quiet = note.velocity <= self.quiet_velocity
        weak = note.confidence <= self.low_confidence
        evidence = {
            "duration": note.duration,
            "velocity": note.velocity,
            "confidence": note.confidence,
        }
        if quiet and weak:
            return (
                CleaningAction.SUPPRESS,
                "micro_note_quiet_low_confidence",
                evidence,
            )
        if quiet:
            return CleaningAction.SUPPRESS, "micro_note_quiet", evidence
        return CleaningAction.UNCERTAIN, "micro_note_possible_ornament", evidence

    def _merge_duplicates(
        self, notes: list[NoteEvent]
    ) -> tuple[list[NoteEvent], list[CleaningDecision]]:
        by_pitch: dict[int, list[NoteEvent]] = {}
        for n in notes:
            by_pitch.setdefault(n.pitch, []).append(n)

        merged: list[NoteEvent] = []
        decisions: list[CleaningDecision] = []
        for pitch, group in by_pitch.items():
            group.sort(key=lambda n: n.start_time)
            cur = group[0]
            for nxt in group[1:]:
                if abs(nxt.start_time - cur.start_time) <= self.merge_threshold_sec:
                    decisions.append(
                        CleaningDecision(
                            note_id=nxt.note_id,
                            pitch=pitch,
                            start_time=nxt.start_time,
                            action=CleaningAction.SUPPRESS,
                            reason="duplicate_same_pitch_onset",
                            evidence={
                                "kept_id": cur.note_id,
                                "onset_delta": abs(nxt.start_time - cur.start_time),
                            },
                        )
                    )
                    cur = NoteEvent(
                        pitch=pitch,
                        start_time=min(cur.start_time, nxt.start_time),
                        end_time=max(cur.end_time, nxt.end_time),
                        velocity=max(cur.velocity, nxt.velocity),
                        confidence=max(cur.confidence, nxt.confidence),
                        note_id=cur.note_id,
                        source_backend=cur.source_backend,
                        original_start_time=cur.original_start_time,
                        original_end_time=max(
                            cur.original_end_time or cur.end_time,
                            nxt.original_end_time or nxt.end_time,
                        ),
                    )
                else:
                    merged.append(cur)
                    cur = nxt
            merged.append(cur)
        return merged, decisions

    def _snap_chord_starts(self, notes: list[NoteEvent]) -> list[NoteEvent]:
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
                    result.append(replace(n, start_time=anchor))
            else:
                result.extend(cluster)
        return result

    def _correct_drift(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        corrected: list[NoteEvent] = []
        for n in notes:
            start = n.start_time
            grid = round(start * 1000) / 1000.0
            if abs(start - grid) <= self.timing_drift_sec:
                start = grid
            corrected.append(replace(n, start_time=start))
        return corrected

    def _classify_octaves(self, notes: list[NoteEvent]) -> list[CleaningDecision]:
        decisions: list[CleaningDecision] = []
        ordered = sorted(notes, key=lambda n: (n.start_time, n.pitch))
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                if b.start_time - a.start_time > self.octave_window_sec:
                    break
                if abs(a.pitch - b.pitch) != 12:
                    continue
                quiet, loud = (a, b) if a.velocity <= b.velocity else (b, a)
                vel_ratio = (quiet.velocity + 1) / (loud.velocity + 1)
                dur_ratio = (min(a.duration, b.duration) + 1e-6) / (
                    max(a.duration, b.duration) + 1e-6
                )
                evidence = {
                    "pair": [a.note_id, b.note_id],
                    "velocity_ratio": vel_ratio,
                    "duration_ratio": dur_ratio,
                    "onset_delta": abs(a.start_time - b.start_time),
                }
                if (
                    vel_ratio <= self.octave_velocity_ratio
                    and dur_ratio <= self.octave_duration_ratio
                    and quiet.confidence < 0.7
                ):
                    action = (
                        CleaningAction.SUPPRESS
                        if self.suppress_octave_ghosts
                        else CleaningAction.UNCERTAIN
                    )
                    reason = "octave_ghost_candidate"
                elif vel_ratio >= 0.6 and dur_ratio >= 0.6:
                    action = CleaningAction.KEEP
                    reason = "octave_doubling"
                else:
                    action = CleaningAction.UNCERTAIN
                    reason = "octave_relation_uncertain"
                decisions.append(
                    CleaningDecision(
                        note_id=quiet.note_id,
                        pitch=quiet.pitch,
                        start_time=quiet.start_time,
                        action=action,
                        reason=reason,
                        evidence=evidence,
                    )
                )
        return decisions
