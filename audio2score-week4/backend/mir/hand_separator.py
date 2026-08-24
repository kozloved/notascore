"""Context-aware piano hand assignment (Viterbi / DP).

Middle C is a weak register prior only. Assignment considers span, motion,
crossing, chord integrity, role, and stream continuity.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Optional

from mir.types import Hand, MusicalEvent, copy_event


@dataclass
class HandSeparatorConfig:
    onset_cluster_beats: float = 0.08
    max_comfortable_span: int = 14
    max_hard_span: int = 19
    register_lh_center: float = 48.0
    register_rh_center: float = 72.0
    register_sigma: float = 18.0
    register_weight: float = 0.35
    motion_weight: float = 1.15
    reach_weight: float = 4.0
    crossing_weight: float = 0.85
    switch_weight: float = 2.4
    chord_split_weight: float = 3.2
    chord_compact_span: int = 12
    discontinuity_weight: float = 1.6
    role_weight: float = 1.15
    direction_weight: float = 1.9
    large_jump_semitones: int = 14
    ambiguous_margin: float = 1.35
    ambiguous_confidence: float = 0.48
    max_full_enum_notes: int = 7


class RegisterSplitHandSeparator:
    """Legacy middle-C split. Kept as a benchmark baseline, not used in production."""

    SPLIT_PITCH = 60

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        result: list[MusicalEvent] = []
        for ev in events:
            if ev.hand not in (Hand.UNKNOWN, Hand.AMBIGUOUS) and ev.hand_confidence >= 0.9:
                result.append(ev)
                continue
            hand = Hand.RIGHT if ev.pitch >= self.SPLIT_PITCH else Hand.LEFT
            result.append(copy_event(ev, hand=hand, hand_confidence=0.4))
        return result


class HandSeparator:
    """Assign LEFT / RIGHT / AMBIGUOUS with a Viterbi path over onset frames."""

    SPLIT_PITCH = 60  # documented weak prior midpoint, not a decision rule

    def __init__(self, config: HandSeparatorConfig | None = None):
        self.config = config or HandSeparatorConfig()

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        if not events:
            return []
        frames = self._cluster(events)
        path, confidences = self._viterbi(frames)
        assigned = self._apply(frames, path, confidences)
        by_id = {id(src): out for src, out in assigned}
        return [by_id.get(id(ev), ev) for ev in events]

    def _cluster(self, events: list[MusicalEvent]) -> list[list[MusicalEvent]]:
        ordered = sorted(events, key=lambda e: (e.start_beat, e.pitch))
        frames: list[list[MusicalEvent]] = []
        for ev in ordered:
            if (
                frames
                and ev.start_beat - frames[-1][0].start_beat
                <= self.config.onset_cluster_beats
            ):
                frames[-1].append(ev)
            else:
                frames.append([ev])
        return frames

    def _candidates(self, notes: list[MusicalEvent]) -> list[tuple[int, ...]]:
        n = len(notes)
        if n == 0:
            return [()]
        if n <= self.config.max_full_enum_notes:
            return [tuple((mask >> i) & 1 for i in range(n)) for mask in range(1 << n)]
        order = sorted(range(n), key=lambda i: notes[i].pitch)
        cands: list[tuple[int, ...]] = []
        for split in range(n + 1):
            assign = [1] * n
            for k, idx in enumerate(order):
                assign[idx] = 0 if k < split else 1
            cands.append(tuple(assign))
        return cands

    def _viterbi(
        self, frames: list[list[MusicalEvent]]
    ) -> tuple[list[tuple[int, ...]], list[float]]:
        cfg = self.config
        states: list[list[tuple[int, ...]]] = [self._candidates(f) for f in frames]
        dp: list[list[float]] = []
        back: list[list[int]] = []
        emit: list[list[float]] = []

        for t, frame in enumerate(frames):
            emit_t = [self._emission(frame, st) for st in states[t]]
            emit.append(emit_t)
            if t == 0:
                dp.append(list(emit_t))
                back.append([-1] * len(states[t]))
                continue
            prev_states = states[t - 1]
            row = []
            prev_idx = []
            for j, st in enumerate(states[t]):
                best = float("inf")
                arg = 0
                for i, pst in enumerate(prev_states):
                    cost = dp[t - 1][i] + emit_t[j] + self._transition(
                        frames[t - 1], pst, frame, st
                    )
                    if cost < best:
                        best = cost
                        arg = i
                row.append(best)
                prev_idx.append(arg)
            dp.append(row)
            back.append(prev_idx)

        last = min(range(len(dp[-1])), key=lambda i: dp[-1][i])
        path_idx = [last]
        for t in range(len(frames) - 1, 0, -1):
            path_idx.append(back[t][path_idx[-1]])
        path_idx.reverse()
        path = [states[t][path_idx[t]] for t in range(len(frames))]

        confidences: list[float] = []
        for t, frame in enumerate(frames):
            costs = dp[t]
            best_i = path_idx[t]
            best = costs[best_i]
            second = min(
                (c for i, c in enumerate(costs) if i != best_i),
                default=best + 8.0,
            )
            margin = second - best
            conf = 1.0 - pow(2.718281828, -max(0.0, margin) / 2.4)
            conf = max(0.15, min(0.99, conf))
            if margin < cfg.ambiguous_margin:
                conf = min(conf, cfg.ambiguous_confidence * 0.9)
            confidences.append(conf)
        return path, confidences

    def _emission(self, notes: list[MusicalEvent], assign: tuple[int, ...]) -> float:
        cfg = self.config
        cost = 0.0
        lh = [n.pitch for n, a in zip(notes, assign) if a == 0]
        rh = [n.pitch for n, a in zip(notes, assign) if a == 1]

        for note, a in zip(notes, assign):
            center = cfg.register_rh_center if a == 1 else cfg.register_lh_center
            dist = (note.pitch - center) / cfg.register_sigma
            cost += cfg.register_weight * dist * dist
            if note.role == "melody" and a == 0:
                cost += cfg.role_weight * 1.4
            elif note.role == "bass" and a == 1:
                cost += cfg.role_weight * 1.4
            elif note.role == "accompaniment" and a == 1 and note.pitch < 55:
                cost += cfg.role_weight * 0.35

        cost += cfg.reach_weight * (
            self._span_penalty(lh) + self._span_penalty(rh)
        )

        if lh and rh:
            cross = max(0, max(lh) - min(rh))
            cost += cfg.crossing_weight * (cross / 6.0)

        all_pitches = sorted(n.pitch for n in notes)
        if len(all_pitches) >= 2:
            span = all_pitches[-1] - all_pitches[0]
            if span <= cfg.chord_compact_span and lh and rh:
                compactness = (cfg.chord_compact_span - span + 1) / cfg.chord_compact_span
                cost += cfg.chord_split_weight * compactness
        return cost

    def _span_penalty(self, pitches: list[int]) -> float:
        if len(pitches) < 2:
            return 0.0
        span = max(pitches) - min(pitches)
        cfg = self.config
        if span <= cfg.max_comfortable_span:
            return 0.0
        extra = span - cfg.max_comfortable_span
        hard = max(0, span - cfg.max_hard_span)
        return extra * extra * 0.35 + hard * 12.0

    def _transition(
        self,
        prev_notes: list[MusicalEvent],
        prev_assign: tuple[int, ...],
        notes: list[MusicalEvent],
        assign: tuple[int, ...],
    ) -> float:
        cfg = self.config
        prev_c = self._centroids(prev_notes, prev_assign)
        curr_c = self._centroids(notes, assign)
        prev_ext = self._extrema(prev_notes, prev_assign)
        cost = 0.0

        for hand in (0, 1):
            pc, cc = prev_c[hand], curr_c[hand]
            if pc is None or cc is None:
                continue
            jump = abs(cc - pc)
            cost += cfg.motion_weight * (jump / 12.0)
            if jump > cfg.large_jump_semitones:
                cost += cfg.motion_weight * ((jump - cfg.large_jump_semitones) / 6.0)

        for note, a in zip(notes, assign):
            nearer = self._nearer_hand(note.pitch, prev_c)
            if nearer is not None and nearer != a:
                gap = abs(
                    (prev_c[nearer] if prev_c[nearer] is not None else note.pitch)
                    - note.pitch
                )
                other = prev_c[a]
                other_gap = abs((other if other is not None else note.pitch) - note.pitch)
                if gap + 3 < other_gap:
                    cost += cfg.switch_weight * ((other_gap - gap) / 8.0)

            disc = 0.0
            if prev_ext[a] is not None:
                disc = abs(note.pitch - prev_ext[a][1 if a == 1 else 0])
            cost += cfg.discontinuity_weight * (min(disc, 24) / 16.0)

        for hand in (0, 1):
            if prev_c[hand] is None or curr_c[hand] is None:
                continue
            prev_dir = prev_ext[hand][1] - prev_ext[hand][0] if prev_ext[hand] else 0
            # previous frame direction from min/max is weak; use centroid delta only
            delta = curr_c[hand] - prev_c[hand]
            if prev_dir == 0:
                continue
            if delta * prev_dir < 0 and abs(delta) > 2:
                cost += cfg.direction_weight * 0.4

        # Prefer matching each current note to the closest previous-hand stream.
        for note, a in zip(notes, assign):
            if prev_c[0] is None or prev_c[1] is None:
                continue
            d_lh = abs(note.pitch - prev_c[0])
            d_rh = abs(note.pitch - prev_c[1])
            natural = 0 if d_lh <= d_rh else 1
            if natural != a and abs(d_lh - d_rh) > 4:
                cost += cfg.direction_weight * (abs(d_lh - d_rh) / 10.0)
        return cost

    def _centroids(
        self, notes: list[MusicalEvent], assign: tuple[int, ...]
    ) -> tuple[Optional[float], Optional[float]]:
        groups: list[list[int]] = [[], []]
        for n, a in zip(notes, assign):
            groups[a].append(n.pitch)
        return (
            mean(groups[0]) if groups[0] else None,
            mean(groups[1]) if groups[1] else None,
        )

    def _extrema(
        self, notes: list[MusicalEvent], assign: tuple[int, ...]
    ) -> tuple[Optional[tuple[int, int]], Optional[tuple[int, int]]]:
        groups: list[list[int]] = [[], []]
        for n, a in zip(notes, assign):
            groups[a].append(n.pitch)
        out: list[Optional[tuple[int, int]]] = []
        for g in groups:
            out.append((min(g), max(g)) if g else None)
        return out[0], out[1]

    def _nearer_hand(
        self, pitch: int, centroids: tuple[Optional[float], Optional[float]]
    ) -> Optional[int]:
        dists = []
        for i, c in enumerate(centroids):
            if c is None:
                continue
            dists.append((abs(pitch - c), i))
        if not dists:
            return None
        dists.sort()
        return dists[0][1]

    def _apply(
        self,
        frames: list[list[MusicalEvent]],
        path: list[tuple[int, ...]],
        confidences: list[float],
    ) -> list[tuple[MusicalEvent, MusicalEvent]]:
        assigned: list[tuple[MusicalEvent, MusicalEvent]] = []
        for frame, assign, conf in zip(frames, path, confidences):
            for note, a in zip(frame, assign):
                if conf < self.config.ambiguous_confidence:
                    hand = Hand.AMBIGUOUS
                    hconf = conf
                else:
                    hand = Hand.RIGHT if a == 1 else Hand.LEFT
                    hconf = conf
                assigned.append(
                    (note, copy_event(note, hand=hand, hand_confidence=round(hconf, 3)))
                )
        return assigned
