"""Clean raw note lists before notation.

Destructive edits are classified KEEP / SUPPRESS / UNCERTAIN with a reason.
Modes:

    strict_safe         technically invalid MIDI only (MT3 default)
    conservative        safe + Basic Pitch artifact cleanup (quiet micros,
                        near-duplicate onsets, quiet octave ghosts)
    legacy_aggressive   historical production cleaner, including chord-start
                        snapping, millisecond drift rounding, and final-note
                        stretching — kept for A/B and explicit opt-in

MIDICleaner() with no arguments stays on legacy_aggressive so existing unit
tests of those rules keep their meaning. Production always constructs the
cleaner via MIDICleaner.for_source().
"""

from __future__ import annotations

from dataclasses import replace
import math
import statistics

from mir.models import CleaningAction, CleaningDecision
from mir.pipeline_config import ValidationMode, parse_validation_mode, resolve_validation_mode
from mir.types import NoteEvent


_MODE_PRESETS: dict[ValidationMode, dict] = {
    ValidationMode.STRICT_SAFE: {
        "merge_threshold_sec": 0.001,
        "min_duration_sec": 0.0,
        "drop_octave_ghosts": False,
        "suppress_octave_ghosts": False,
        "trim_overlaps": True,
        "stretch_final_note": False,
        "snap_chords": False,
        "correct_drift": False,
        "suppress_quiet_micros": False,
        "preserve_uncertain": True,
    },
    ValidationMode.CONSERVATIVE: {
        "merge_threshold_sec": 0.025,
        "min_duration_sec": 0.04,
        "drop_octave_ghosts": True,
        "suppress_octave_ghosts": False,
        "trim_overlaps": True,
        "stretch_final_note": False,
        "snap_chords": False,
        "correct_drift": False,
        "suppress_quiet_micros": True,
        "preserve_uncertain": True,
    },
    ValidationMode.LEGACY_AGGRESSIVE: {
        "merge_threshold_sec": 0.025,
        "min_duration_sec": 0.04,
        "drop_octave_ghosts": True,
        "suppress_octave_ghosts": False,
        "trim_overlaps": True,
        "stretch_final_note": True,
        "snap_chords": True,
        "correct_drift": True,
        "suppress_quiet_micros": True,
        "preserve_uncertain": True,
    },
}


class MIDICleaner:
    """Merge duplicates, drop quiet micro-notes, group chords, preserve expressivity."""

    def __init__(
        self,
        merge_threshold_sec: float | None = None,
        min_duration_sec: float | None = None,
        chord_window_sec: float = 0.05,
        timing_drift_sec: float = 0.015,
        quiet_velocity: int = 42,
        low_confidence: float = 0.45,
        preserve_uncertain: bool | None = None,
        suppress_octave_ghosts: bool | None = None,
        octave_window_sec: float = 0.05,
        octave_duration_ratio: float = 0.55,
        octave_velocity_ratio: float = 0.38,
        octave_keep_ratio: float = 0.6,
        drop_octave_ghosts: bool | None = None,
        trim_overlaps: bool | None = None,
        stretch_final_note: bool | None = None,
        snap_chords: bool | None = None,
        correct_drift: bool | None = None,
        suppress_quiet_micros: bool | None = None,
        shadow_mode: bool = False,
        mode: str | ValidationMode | None = None,
        source_backend: str = "unknown",
    ):
        resolved = (
            parse_validation_mode(mode)
            if mode is not None
            else ValidationMode.LEGACY_AGGRESSIVE
        )
        if resolved is None:
            resolved = ValidationMode.LEGACY_AGGRESSIVE
        preset = dict(_MODE_PRESETS[resolved])
        self.mode = resolved
        self.source_backend = source_backend
        self.merge_threshold_sec = (
            preset["merge_threshold_sec"]
            if merge_threshold_sec is None
            else merge_threshold_sec
        )
        self.min_duration_sec = (
            preset["min_duration_sec"] if min_duration_sec is None else min_duration_sec
        )
        self.chord_window_sec = chord_window_sec
        self.timing_drift_sec = timing_drift_sec
        self.quiet_velocity = quiet_velocity
        self.low_confidence = low_confidence
        self.preserve_uncertain = (
            preset["preserve_uncertain"]
            if preserve_uncertain is None
            else preserve_uncertain
        )
        self.suppress_octave_ghosts = (
            preset["suppress_octave_ghosts"]
            if suppress_octave_ghosts is None
            else suppress_octave_ghosts
        )
        self.octave_window_sec = octave_window_sec
        self.octave_duration_ratio = octave_duration_ratio
        self.octave_velocity_ratio = octave_velocity_ratio
        self.octave_keep_ratio = octave_keep_ratio
        self.drop_octave_ghosts = (
            preset["drop_octave_ghosts"]
            if drop_octave_ghosts is None
            else drop_octave_ghosts
        )
        self.trim_overlaps = (
            preset["trim_overlaps"] if trim_overlaps is None else trim_overlaps
        )
        self.stretch_final_note = (
            preset["stretch_final_note"]
            if stretch_final_note is None
            else stretch_final_note
        )
        self.snap_chords = preset["snap_chords"] if snap_chords is None else snap_chords
        self.correct_drift = (
            preset["correct_drift"] if correct_drift is None else correct_drift
        )
        self.suppress_quiet_micros = (
            preset["suppress_quiet_micros"]
            if suppress_quiet_micros is None
            else suppress_quiet_micros
        )
        self.shadow_mode = shadow_mode

    @classmethod
    def for_source(
        cls,
        source_backend: str,
        mode: str | ValidationMode | None = None,
        **kwargs,
    ) -> "MIDICleaner":
        resolved = resolve_validation_mode(source_backend, mode)
        return cls(mode=resolved, source_backend=source_backend, **kwargs)

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

        tagged, sanitize_decisions = self._sanitize_invalid(tagged)
        decisions.extend(sanitize_decisions)

        for n in tagged:
            action, reason, evidence = self._classify_micro(n)
            if (
                action == CleaningAction.SUPPRESS
                and not self.suppress_quiet_micros
            ):
                action = CleaningAction.UNCERTAIN
                reason = f"{reason}_observation"
                evidence = {**evidence, "applied": False, "mode": self.mode.value}
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

        ghost_kept, ghost_decisions = self._drop_octave_ghosts_with_report(kept)
        if self.drop_octave_ghosts and not self.shadow_mode:
            kept = ghost_kept
            decisions.extend(ghost_decisions)
        else:
            for d in ghost_decisions:
                decisions.append(
                    CleaningDecision(
                        note_id=d.note_id,
                        pitch=d.pitch,
                        start_time=d.start_time,
                        action=CleaningAction.UNCERTAIN,
                        reason="octave_ghost_observation",
                        evidence={**d.evidence, "applied": False, "mode": self.mode.value},
                    )
                )

        if self.trim_overlaps:
            kept = self._trim_same_pitch_overlaps(kept)

        if self.snap_chords:
            kept = self._snap_chord_starts(kept)
        else:
            decisions.extend(self._observe_chord_snaps(kept))

        if self.correct_drift:
            kept = self._correct_drift(kept)

        if self.stretch_final_note:
            kept = self._stretch_short_final_note(kept)
        else:
            decisions.extend(self._observe_final_stretch(kept))

        octave_decisions = self._classify_octaves(kept)
        decisions.extend(octave_decisions)
        if self.suppress_octave_ghosts and not self.drop_octave_ghosts and not self.shadow_mode:
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

    def _sanitize_invalid(
        self, notes: list[NoteEvent]
    ) -> tuple[list[NoteEvent], list[CleaningDecision]]:
        """Technically invalid MIDI: NaNs, impossible pitch/velocity/duration."""
        kept: list[NoteEvent] = []
        decisions: list[CleaningDecision] = []
        for n in notes:
            if not _finite(n.start_time) or not _finite(n.end_time):
                decisions.append(
                    CleaningDecision(
                        note_id=n.note_id,
                        pitch=int(n.pitch) if _finite(n.pitch) else -1,
                        start_time=0.0,
                        action=CleaningAction.SUPPRESS,
                        reason="invalid_non_finite_time",
                        evidence={"start_time": n.start_time, "end_time": n.end_time},
                    )
                )
                continue
            pitch = int(n.pitch)
            velocity = int(n.velocity)
            start = float(n.start_time)
            end = float(n.end_time)
            changes: list[str] = []
            if pitch < 0 or pitch > 127:
                clamped = max(0, min(127, pitch))
                changes.append(f"pitch {pitch}->{clamped}")
                pitch = clamped
            if velocity < 1 or velocity > 127:
                clamped_v = max(1, min(127, velocity))
                changes.append(f"velocity {velocity}->{clamped_v}")
                velocity = clamped_v
            if start < 0:
                changes.append(f"start {start}->0")
                start = 0.0
            if end <= start:
                new_end = start + 0.01
                changes.append(f"duration {end - start}->{new_end - start}")
                end = new_end
            note = n
            if changes:
                note = replace(
                    n,
                    pitch=pitch,
                    velocity=velocity,
                    start_time=start,
                    end_time=end,
                )
                decisions.append(
                    CleaningDecision(
                        note_id=n.note_id,
                        pitch=pitch,
                        start_time=start,
                        action=CleaningAction.KEEP,
                        reason="invalid_midi_clamped",
                        evidence={"changes": changes},
                    )
                )
            kept.append(note)
        return kept, decisions

    def _classify_micro(
        self, note: NoteEvent
    ) -> tuple[CleaningAction, str, dict]:
        threshold = self.min_duration_sec if self.min_duration_sec > 0 else 0.04
        if note.duration >= threshold:
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
                                "threshold_sec": self.merge_threshold_sec,
                                "mode": self.mode.value,
                            },
                        )
                    )
                    cur = replace(
                        cur,
                        start_time=min(cur.start_time, nxt.start_time),
                        end_time=max(cur.end_time, nxt.end_time),
                        velocity=max(cur.velocity, nxt.velocity),
                        confidence=max(cur.confidence, nxt.confidence),
                        original_start_time=(
                            cur.original_start_time
                            if cur.original_start_time is not None
                            else cur.start_time
                        ),
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

    @staticmethod
    def _strength(note: NoteEvent) -> float:
        if 0.0 < note.confidence < 1.0:
            return float(note.confidence)
        return max(int(note.velocity), 1) / 127.0

    def _drop_octave_ghosts(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        kept, _ = self._drop_octave_ghosts_with_report(notes)
        return kept

    def _drop_octave_ghosts_with_report(
        self, notes: list[NoteEvent]
    ) -> tuple[list[NoteEvent], list[CleaningDecision]]:
        """Drop quieter ±12/±24 copies that start with a stronger note.

        Similar-strength octaves (real doubled piano writing) are kept.
        A note is never dropped if it is the only remaining pitch covering
        its time span.
        """
        if len(notes) < 2:
            return notes, []

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

        decisions: list[CleaningDecision] = []
        kept: list[NoteEvent] = []
        for idx, n in enumerate(notes):
            if keep[idx]:
                kept.append(n)
                continue
            decisions.append(
                CleaningDecision(
                    note_id=n.note_id,
                    pitch=n.pitch,
                    start_time=n.start_time,
                    action=CleaningAction.SUPPRESS,
                    reason="octave_ghost",
                    evidence={"strength": self._strength(n)},
                )
            )
        return kept, decisions

    def _trim_same_pitch_overlaps(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        """Piano cannot retrigger the same key while it is still down."""
        by_pitch: dict[int, list[NoteEvent]] = {}
        for n in notes:
            by_pitch.setdefault(int(n.pitch), []).append(n)

        trimmed: list[NoteEvent] = []
        for group in by_pitch.values():
            group.sort(key=lambda n: n.start_time)
            current: list[NoteEvent] = []
            for n in group:
                if current and n.start_time < current[-1].end_time:
                    prev = current[-1]
                    current[-1] = replace(
                        prev,
                        end_time=max(prev.start_time + 0.01, n.start_time),
                    )
                current.append(n)
            trimmed.extend(current)
        return trimmed

    def _stretch_short_final_note(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        if len(notes) < 3:
            return notes
        last = max(notes, key=lambda n: n.start_time)
        others = [n.duration for n in notes if n is not last]
        if not others:
            return notes
        typical = statistics.median(others)
        if last.duration >= typical:
            return notes
        return [
            replace(n, end_time=n.start_time + typical) if n is last else n
            for n in notes
        ]

    def _observe_final_stretch(self, notes: list[NoteEvent]) -> list[CleaningDecision]:
        if len(notes) < 3:
            return []
        last = max(notes, key=lambda n: n.start_time)
        others = [n.duration for n in notes if n is not last]
        if not others:
            return []
        typical = statistics.median(others)
        if last.duration >= typical:
            return []
        return [
            CleaningDecision(
                note_id=last.note_id,
                pitch=last.pitch,
                start_time=last.start_time,
                action=CleaningAction.UNCERTAIN,
                reason="final_note_stretch_skipped",
                evidence={
                    "duration": last.duration,
                    "typical": typical,
                    "applied": False,
                    "mode": self.mode.value,
                },
            )
        ]

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

    def _observe_chord_snaps(self, notes: list[NoteEvent]) -> list[CleaningDecision]:
        """Report cluster candidates without moving onsets (safe/conservative)."""
        if len(notes) < 2:
            return []
        sorted_notes = sorted(notes, key=lambda n: n.start_time)
        decisions: list[CleaningDecision] = []
        cluster = [sorted_notes[0]]
        for n in sorted_notes[1:] + [None]:  # type: ignore[list-item]
            if n is not None and n.start_time - cluster[0].start_time <= self.chord_window_sec:
                cluster.append(n)
                continue
            if len(cluster) >= 2:
                starts = [c.start_time for c in cluster]
                if max(starts) - min(starts) > 1e-9:
                    for c in cluster:
                        decisions.append(
                            CleaningDecision(
                                note_id=c.note_id,
                                pitch=c.pitch,
                                start_time=c.start_time,
                                action=CleaningAction.UNCERTAIN,
                                reason="chord_start_snap_skipped",
                                evidence={
                                    "cluster_size": len(cluster),
                                    "spread_sec": max(starts) - min(starts),
                                    "applied": False,
                                    "mode": self.mode.value,
                                },
                            )
                        )
            cluster = [n] if n is not None else []
        return decisions

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
                    "applied": bool(self.suppress_octave_ghosts),
                    "mode": self.mode.value,
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


def _finite(value: float) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
