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
    register_weight: float = 1.05
    motion_weight: float = 0.85
    reach_weight: float = 4.0
    crossing_weight: float = 0.55
    switch_weight: float = 2.8
    chord_split_weight: float = 4.5
    chord_compact_span: int = 12
    discontinuity_weight: float = 0.6
    role_weight: float = 2.2
    direction_weight: float = 2.2
    large_jump_semitones: int = 14
    ambiguous_margin: float = 0.4
    ambiguous_confidence: float = 0.4
    max_full_enum_notes: int = 7
    lh_comfort_max: int = 67
    rh_comfort_min: int = 52


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
            if a == 0 and note.pitch > cfg.lh_comfort_max:
                cost += 0.45 * (note.pitch - cfg.lh_comfort_max)
            if a == 1 and note.pitch < cfg.rh_comfort_min:
                cost += 0.45 * (cfg.rh_comfort_min - note.pitch)
            if note.role == "melody" and a == 0:
                cost += cfg.role_weight * 1.6
            elif note.role == "bass" and a == 1:
                cost += cfg.role_weight * 1.6
            elif note.role == "accompaniment" and a == 1 and note.pitch <= 64:
                cost += cfg.role_weight * 0.8

        cost += cfg.reach_weight * (self._span_penalty(lh) + self._span_penalty(rh))

        if lh and rh:
            cross = max(0, max(lh) - min(rh))
            cost += cfg.crossing_weight * (cross / 6.0)

        # Keep pitch-proximate chord tones in the same hand, unless roles conflict.
        ordered = sorted(zip(notes, assign), key=lambda x: x[0].pitch)
        component: list = []
        for item in ordered:
            if component and item[0].pitch - component[-1][0].pitch <= 5:
                component.append(item)
            else:
                if component:
                    cost += self._component_split_cost(component)
                component = [item]
        if component:
            cost += self._component_split_cost(component)
        return cost

    def _component_split_cost(self, component: list) -> float:
        if len(component) < 2:
            return 0.0
        roles = {n.role for n, _ in component if n.role}
        if "melody" in roles and ("bass" in roles or "accompaniment" in roles):
            return 0.0
        hands = {a for _, a in component}
        if len(hands) == 1:
            return 0.0
        span = component[-1][0].pitch - component[0][0].pitch
        if span > self.config.chord_compact_span:
            return 0.0
        return self.config.chord_split_weight * (1.0 + 0.25 * len(component))

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
        cost = 0.0

        for hand in (0, 1):
            pc, cc = prev_c[hand], curr_c[hand]
            if pc is not None and cc is not None:
                jump = abs(cc - pc)
                cost += cfg.motion_weight * (jump / 12.0)
                if jump > cfg.large_jump_semitones:
                    cost += cfg.motion_weight * ((jump - cfg.large_jump_semitones) / 5.0)

        # Prefer continuing a hand rather than activating the unused one
        # unless the leap on the current hand would be large.
        for note, a in zip(notes, assign):
            other = 1 - a
            if prev_c[a] is None and prev_c[other] is not None:
                stay_jump = abs(note.pitch - prev_c[other])
                if stay_jump <= cfg.large_jump_semitones:
                    cost += cfg.switch_weight * (1.0 - stay_jump / 24.0)

            if prev_c[0] is not None and prev_c[1] is not None:
                d_lh = abs(note.pitch - prev_c[0])
                d_rh = abs(note.pitch - prev_c[1])
                natural = 0 if d_lh <= d_rh else 1
                if natural != a and abs(d_lh - d_rh) > 3:
                    cost += cfg.direction_weight * (abs(d_lh - d_rh) / 10.0)
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
        for frame, assign in zip(frames, path):
            for i, (note, a) in enumerate(zip(frame, assign)):
                flipped = list(assign)
                flipped[i] = 1 - a
                margin = self._emission(frame, tuple(flipped)) - self._emission(
                    frame, assign
                )
                conf = 1.0 - pow(2.718281828, -max(0.0, margin) / 1.6)
                conf = max(0.2, min(0.99, conf))
                hand = Hand.RIGHT if a == 1 else Hand.LEFT
                if (
                    margin < self.config.ambiguous_margin
                    and not note.role
                    and 55 <= note.pitch <= 65
                ):
                    hand = Hand.AMBIGUOUS
                    conf = min(conf, 0.45)
                assigned.append(
                    (note, copy_event(note, hand=hand, hand_confidence=round(conf, 3)))
                )
        return assigned
