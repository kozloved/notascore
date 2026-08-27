"""Context-aware piano hand assignment (Viterbi / DP).

Middle C is a weak register prior only. Assignment considers span, motion,
crossing, chord integrity, role, and stream continuity.

Incoming LEFT/RIGHT is a hint unless `hand_locked` is set by an explicit
external source. Musical roles never lock a hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp
from statistics import mean
from typing import Optional

from mir.types import Hand, MusicalEvent, copy_event

LH, RH = 0, 1


@dataclass
class HandReps:
    """Carried Viterbi state: last pitch and velocity of each hand."""

    lh: Optional[float] = None
    rh: Optional[float] = None
    lh_vel: float = 0.0
    rh_vel: float = 0.0


@dataclass
class HandSeparatorConfig:
    onset_cluster_beats: float = 0.08
    max_comfortable_span: int = 24
    max_hard_span: int = 31
    register_lh_center: float = 48.0
    register_rh_center: float = 72.0
    register_sigma: float = 18.0
    register_weight: float = 1.05
    motion_weight: float = 0.95
    reach_weight: float = 2.4
    crossing_weight: float = 0.22
    switch_weight: float = 3.6
    chord_split_weight: float = 6.2
    chord_gap: int = 7
    chord_compact_span: int = 16
    role_weight: float = 0.85
    incoming_hand_weight: float = 0.55
    direction_weight: float = 3.2
    trajectory_weight: float = 2.8
    large_jump_semitones: int = 14
    ambiguous_margin: float = 0.55
    ambiguous_confidence: float = 0.45
    ambiguous_pitch_lo: int = 55
    ambiguous_pitch_hi: int = 67
    max_full_enum_notes: int = 7
    lh_comfort_max: int = 67
    rh_comfort_min: int = 52


@dataclass
class HandDecision:
    note_id: str
    pitch: int
    start_beat: float
    selected: str
    confidence: float
    competing_hand: str
    competing_cost_delta: float
    factors: dict = field(default_factory=dict)


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

    def __init__(self, config: HandSeparatorConfig | None = None):
        self.config = config or HandSeparatorConfig()
        self.last_decisions: list[HandDecision] = []
        self._afterbeats_to_rh = False

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        self.last_decisions = []
        self._afterbeats_to_rh = False
        if not events:
            return []
        frames = self._cluster(events)
        self._afterbeats_to_rh = any(self._frame_has_bass_octave(f) for f in frames)
        path, confidences, carries = self._viterbi(frames)
        assigned = self._apply(frames, path, confidences)
        by_id = {id(src): out for src, out in assigned}
        result: list[MusicalEvent] = []
        for ev in events:
            out = by_id.get(id(ev), ev)
            if self._is_locked(ev):
                result.append(
                    copy_event(
                        out,
                        hand=ev.hand,
                        hand_confidence=max(ev.hand_confidence, 0.95),
                    )
                )
            else:
                result.append(out)
        return result

    @staticmethod
    def _is_locked(ev: MusicalEvent) -> bool:
        return bool(getattr(ev, "hand_locked", False)) and ev.hand in (
            Hand.LEFT,
            Hand.RIGHT,
        )

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

    def _locked_bits(self, notes: list[MusicalEvent]) -> dict[int, int]:
        locked: dict[int, int] = {}
        for i, n in enumerate(notes):
            if self._is_locked(n):
                locked[i] = RH if n.hand == Hand.RIGHT else LH

        # Bass octaves (higher at or below E3) stay entirely in the left hand.
        for i, a in enumerate(notes):
            for j, b in enumerate(notes):
                if i >= j:
                    continue
                lower, higher = (a, b) if a.pitch <= b.pitch else (b, a)
                if higher.pitch - lower.pitch == 12 and higher.pitch <= 52:
                    locked[i] = LH
                    locked[j] = LH

        # Waltz / oom-pah: once bass octaves exist, mid-register chords with
        # no bass note are afterbeats and belong in the right hand.
        if (
            self._afterbeats_to_rh
            and len(notes) >= 2
            and all(n.pitch >= 53 for n in notes)
        ):
            for i in range(len(notes)):
                locked.setdefault(i, RH)
        return locked

    @staticmethod
    def _frame_has_bass_octave(notes: list[MusicalEvent]) -> bool:
        for i, a in enumerate(notes):
            for b in notes[i + 1 :]:
                lower, higher = (a, b) if a.pitch <= b.pitch else (b, a)
                if higher.pitch - lower.pitch == 12 and higher.pitch <= 52:
                    return True
        return False

    def _candidates(self, notes: list[MusicalEvent]) -> list[tuple[int, ...]]:
        n = len(notes)
        if n == 0:
            return [()]
        locked = self._locked_bits(notes)
        if n <= self.config.max_full_enum_notes:
            raw = [tuple((mask >> i) & 1 for i in range(n)) for mask in range(1 << n)]
        else:
            order = sorted(range(n), key=lambda i: notes[i].pitch)
            raw = []
            for split in range(n + 1):
                assign = [RH] * n
                for k, idx in enumerate(order):
                    assign[idx] = LH if k < split else RH
                raw.append(tuple(assign))
        filtered = [
            cand
            for cand in raw
            if all(cand[i] == bit for i, bit in locked.items())
        ]
        return filtered or raw[:1]

    def _viterbi(
        self, frames: list[list[MusicalEvent]]
    ) -> tuple[list[tuple[int, ...]], list[float], list[HandReps]]:
        cfg = self.config
        states: list[list[tuple[int, ...]]] = [self._candidates(f) for f in frames]
        dp: list[list[float]] = []
        back: list[list[int]] = []
        carry: list[list[HandReps]] = []

        for t, frame in enumerate(frames):
            emit_t = [self._emission(frame, st) for st in states[t]]
            if t == 0:
                dp.append(list(emit_t))
                back.append([-1] * len(states[t]))
                carry.append(
                    [self._update_reps(HandReps(), frame, st) for st in states[t]]
                )
                continue
            row = []
            prev_idx = []
            row_carry: list[HandReps] = []
            for j, st in enumerate(states[t]):
                best = float("inf")
                arg = 0
                best_rep = HandReps()
                for i, _pst in enumerate(states[t - 1]):
                    prev = carry[t - 1][i]
                    cost = dp[t - 1][i] + emit_t[j] + self._transition(prev, frame, st)
                    if cost < best:
                        best = cost
                        arg = i
                        best_rep = self._update_reps(prev, frame, st)
                row.append(best)
                prev_idx.append(arg)
                row_carry.append(best_rep)
            dp.append(row)
            back.append(prev_idx)
            carry.append(row_carry)

        last = min(range(len(dp[-1])), key=lambda i: dp[-1][i])
        path_idx = [last]
        for t in range(len(frames) - 1, 0, -1):
            path_idx.append(back[t][path_idx[-1]])
        path_idx.reverse()
        path = [states[t][path_idx[t]] for t in range(len(frames))]
        carries = [carry[t][path_idx[t]] for t in range(len(frames))]

        confidences: list[float] = []
        for t in range(len(frames)):
            costs = dp[t]
            best_i = path_idx[t]
            best = costs[best_i]
            second = min(
                (c for i, c in enumerate(costs) if i != best_i),
                default=best + 8.0,
            )
            margin = second - best
            conf = 1.0 - exp(-max(0.0, margin) / 2.4)
            conf = max(0.15, min(0.99, conf))
            if margin < cfg.ambiguous_margin:
                conf = min(conf, cfg.ambiguous_confidence)
            confidences.append(conf)
        return path, confidences, carries

    def _emission(self, notes: list[MusicalEvent], assign: tuple[int, ...]) -> float:
        cfg = self.config
        cost = 0.0
        lh = [n.pitch for n, a in zip(notes, assign) if a == LH]
        rh = [n.pitch for n, a in zip(notes, assign) if a == RH]

        for note, a in zip(notes, assign):
            cost += self._register_cost(note.pitch, a)
            cost += self._role_cost(note, a)
            cost += self._incoming_hint_cost(note, a)

        cost += cfg.reach_weight * (self._span_penalty(lh) + self._span_penalty(rh))

        if len(notes) == 2 and assign[0] == assign[1]:
            span = abs(notes[0].pitch - notes[1].pitch)
            if span >= 19:
                cost += 5.0

        if lh and rh:
            cross = max(0, max(lh) - min(rh))
            cost += cfg.crossing_weight * (cross / 6.0)

        ordered = sorted(zip(notes, assign), key=lambda x: x[0].pitch)
        component: list = []
        for item in ordered:
            if component and item[0].pitch - component[-1][0].pitch <= cfg.chord_gap:
                component.append(item)
            else:
                if component:
                    cost += self._component_split_cost(component)
                component = [item]
        if component:
            cost += self._component_split_cost(component)
        return cost

    def _register_cost(self, pitch: int, hand: int) -> float:
        cfg = self.config
        center = cfg.register_rh_center if hand == RH else cfg.register_lh_center
        dist = (pitch - center) / cfg.register_sigma
        cost = cfg.register_weight * dist * dist
        if hand == LH and pitch > cfg.lh_comfort_max:
            cost += 0.35 * (pitch - cfg.lh_comfort_max)
        if hand == RH and pitch < cfg.rh_comfort_min:
            cost += 0.35 * (cfg.rh_comfort_min - pitch)
        return cost

    def _role_cost(self, note: MusicalEvent, hand: int) -> float:
        cfg = self.config
        if note.role == "melody" and hand == LH:
            return cfg.role_weight * 1.15
        if note.role == "bass" and hand == RH:
            return cfg.role_weight * 1.15
        if note.role == "accompaniment" and hand == RH and note.pitch <= 64:
            return cfg.role_weight * 1.05
        return 0.0

    def _incoming_hint_cost(self, note: MusicalEvent, hand: int) -> float:
        if self._is_locked(note):
            return 0.0
        if note.hand == Hand.LEFT and hand == RH:
            return self.config.incoming_hand_weight
        if note.hand == Hand.RIGHT and hand == LH:
            return self.config.incoming_hand_weight
        return 0.0

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
        prev: HandReps,
        notes: list[MusicalEvent],
        assign: tuple[int, ...],
    ) -> float:
        cfg = self.config
        curr = self._centroids(notes, assign)
        cost = 0.0
        prev_pitch = (prev.lh, prev.rh)
        prev_vel = (prev.lh_vel, prev.rh_vel)

        for hand, cc in ((LH, curr[LH]), (RH, curr[RH])):
            prior = prev_pitch[hand]
            if prior is not None and cc is not None:
                jump = abs(cc - prior)
                cost += cfg.motion_weight * (jump / 12.0)
                if jump > cfg.large_jump_semitones:
                    cost += cfg.motion_weight * ((jump - cfg.large_jump_semitones) / 5.0)
                predicted = prior + prev_vel[hand]
                reversing = (cc - prior) * prev_vel[hand] < 0 and abs(cc - prior) > 8
                if not reversing:
                    cost += cfg.trajectory_weight * (abs(cc - predicted) / 12.0)

        for note, a in zip(notes, assign):
            my_prev = prev_pitch[a]
            other_prev = prev_pitch[1 - a]
            if my_prev is None and other_prev is not None:
                stay_jump = abs(note.pitch - other_prev)
                # Opening a silent hand is expensive if the active hand can still
                # reach this pitch. True opposite-register entries stay cheap.
                if stay_jump <= 28:
                    cost += cfg.switch_weight * max(0.0, 1.0 - stay_jump / 28.0)
            if prev.lh is not None and prev.rh is not None:
                pred_lh = prev.lh + prev.lh_vel
                pred_rh = prev.rh + prev.rh_vel
                d_lh = abs(note.pitch - pred_lh)
                d_rh = abs(note.pitch - pred_rh)
                natural = LH if d_lh <= d_rh else RH
                if natural != a:
                    cost += cfg.direction_weight * (abs(d_lh - d_rh) / 8.0)

        nxt = self._update_reps(prev, notes, assign)
        if nxt.lh is not None and nxt.rh is not None and nxt.lh > nxt.rh + 1.0:
            # Persistent crossing is penalized more than a first crossing frame.
            persistent = prev.lh is not None and prev.rh is not None and prev.lh > prev.rh
            scale = 1.6 if persistent else 0.45
            cost += cfg.crossing_weight * scale * ((nxt.lh - nxt.rh) / 6.0)
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
        return extra * extra * 0.18 + hard * 2.5

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

    def _update_reps(
        self,
        prev: HandReps,
        notes: list[MusicalEvent],
        assign: tuple[int, ...],
    ) -> HandReps:
        curr_lh, curr_rh = self._centroids(notes, assign)
        lh_vel = prev.lh_vel
        rh_vel = prev.rh_vel
        if curr_lh is not None and prev.lh is not None:
            lh_vel = curr_lh - prev.lh
        elif curr_lh is None:
            curr_lh = prev.lh
        if curr_rh is not None and prev.rh is not None:
            rh_vel = curr_rh - prev.rh
        elif curr_rh is None:
            curr_rh = prev.rh
        return HandReps(lh=curr_lh, rh=curr_rh, lh_vel=lh_vel, rh_vel=rh_vel)

    def _note_factors(
        self,
        note: MusicalEvent,
        hand: int,
        prev: HandReps,
    ) -> dict:
        prior = prev.rh if hand == RH else prev.lh
        vel = prev.rh_vel if hand == RH else prev.lh_vel
        motion = 0.0
        traj = 0.0
        if prior is not None:
            motion = self.config.motion_weight * (abs(note.pitch - prior) / 12.0)
            traj = self.config.trajectory_weight * (
                abs(note.pitch - (prior + vel)) / 12.0
            )
        return {
            "register": round(self._register_cost(note.pitch, hand), 3),
            "motion": round(motion, 3),
            "trajectory": round(traj, 3),
            "role": round(self._role_cost(note, hand), 3),
            "incoming_hint": round(self._incoming_hint_cost(note, hand), 3),
        }

    def _apply(
        self,
        frames: list[list[MusicalEvent]],
        path: list[tuple[int, ...]],
        confidences: list[float],
    ) -> list[tuple[MusicalEvent, MusicalEvent]]:
        assigned: list[tuple[MusicalEvent, MusicalEvent]] = []
        decisions: list[HandDecision] = []
        prev = HandReps()
        for frame, assign, frame_conf in zip(frames, path, confidences):
            for i, (note, a) in enumerate(zip(frame, assign)):
                flipped = list(assign)
                flipped[i] = 1 - a
                chosen_e = self._emission(frame, assign)
                flip_e = self._emission(frame, tuple(flipped))
                chosen_t = self._transition(prev, frame, assign)
                flip_t = self._transition(prev, frame, tuple(flipped))
                margin = (flip_e + flip_t) - (chosen_e + chosen_t)
                conf = 1.0 - exp(-max(0.0, margin) / 1.6)
                conf = max(0.18, min(0.99, conf))
                conf = min(conf, frame_conf + 0.15)
                hand = Hand.RIGHT if a == RH else Hand.LEFT
                competing = Hand.LEFT if a == RH else Hand.RIGHT
                in_middle = (
                    self.config.ambiguous_pitch_lo
                    <= note.pitch
                    <= self.config.ambiguous_pitch_hi
                )
                isolated = len(frame) == 1
                if (
                    not self._is_locked(note)
                    and isolated
                    and in_middle
                    and margin < self.config.ambiguous_margin
                ):
                    hand = Hand.AMBIGUOUS
                    conf = min(conf, self.config.ambiguous_confidence)
                assigned.append(
                    (note, copy_event(note, hand=hand, hand_confidence=round(conf, 3)))
                )
                decisions.append(
                    HandDecision(
                        note_id=note.note_id,
                        pitch=note.pitch,
                        start_beat=note.start_beat,
                        selected=hand.value,
                        confidence=round(conf, 3),
                        competing_hand=competing.value,
                        competing_cost_delta=round(margin, 3),
                        factors=self._note_factors(note, a, prev),
                    )
                )
            prev = self._update_reps(prev, frame, assign)
        self.last_decisions = decisions
        return assigned
