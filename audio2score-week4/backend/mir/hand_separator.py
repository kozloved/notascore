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
    """Carried Viterbi state: last pitch/velocity plus register anchors.

    `lh_bass` / `rh_melody` remember the last clearly-bass / clearly-melody
    pitches so a single mid-register mis-assignment cannot erase the texture.
    Beat timestamps enable silence decay; held-key reach is not modeled here.
    """

    lh: Optional[float] = None
    rh: Optional[float] = None
    lh_vel: float = 0.0
    rh_vel: float = 0.0
    lh_bass: Optional[float] = None
    rh_melody: Optional[float] = None
    last_beat: Optional[float] = None
    lh_beat: Optional[float] = None
    rh_beat: Optional[float] = None
    lh_bass_beat: Optional[float] = None
    rh_melody_beat: Optional[float] = None


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
    max_unlocked_enum: int = 8
    lh_comfort_max: int = 67
    rh_comfort_min: int = 52
    # Simultaneous bass+upper textures and broken-chord LH streams.
    bass_register_max: int = 52
    melody_register_min: int = 67
    same_hand_span_soft: int = 14
    same_hand_span_weight: float = 0.45
    bass_melody_same_hand_weight: float = 7.0
    accomp_stream_weight: float = 4.2
    accomp_rise_max: int = 24
    accomp_drop_min: int = 8
    # Silence / phrase decay for carried anchors.
    silence_soft_beats: float = 2.0
    silence_hard_beats: float = 4.0
    silence_decay_tau: float = 1.75


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
        self.last_source: str = "viterbi"

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        self.last_decisions = []
        if not events:
            return []
        frames = self._cluster(events)
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
        return locked

    def _candidates(self, notes: list[MusicalEvent]) -> list[tuple[int, ...]]:
        """Return hand assignments that always respect explicit locks.

        Dense frames no longer fall back to contiguous pitch splits that can
        violate interleaved locks. Unlocked notes are enumerated or split on
        pitch among themselves, then merged with fixed locked bits.
        """
        n = len(notes)
        if n == 0:
            return [()]
        locked = self._locked_bits(notes)
        unlocked = [i for i in range(n) if i not in locked]

        def merge(unlocked_assign: tuple[int, ...]) -> tuple[int, ...]:
            out = [RH] * n
            for i, bit in locked.items():
                out[i] = bit
            for idx, bit in zip(unlocked, unlocked_assign):
                out[idx] = bit
            return tuple(out)

        if not unlocked:
            return [merge(())]

        if len(unlocked) <= self.config.max_unlocked_enum and (
            n <= self.config.max_full_enum_notes or locked
        ):
            raw = [
                merge(tuple((mask >> k) & 1 for k in range(len(unlocked))))
                for mask in range(1 << len(unlocked))
            ]
        elif n <= self.config.max_full_enum_notes and not locked:
            raw = [tuple((mask >> i) & 1 for i in range(n)) for mask in range(1 << n)]
        else:
            order = sorted(unlocked, key=lambda i: notes[i].pitch)
            raw = []
            for split in range(len(order) + 1):
                bits = [RH] * len(order)
                for k in range(split):
                    bits[k] = LH
                # Map pitch-ordered unlocked bits back to unlocked index order.
                by_order = {idx: bits[pos] for pos, idx in enumerate(order)}
                raw.append(merge(tuple(by_order[i] for i in unlocked)))

        filtered = [
            cand
            for cand in raw
            if all(cand[i] == bit for i, bit in locked.items())
        ]
        if filtered:
            return filtered
        # Last resort: still lock-respecting (unlocked default to RH).
        return [merge(tuple(RH for _ in unlocked))]

    def _silence_scale(self, prev: HandReps, frame_beat: float) -> float:
        if prev.last_beat is None:
            return 1.0
        dt = max(0.0, frame_beat - prev.last_beat)
        cfg = self.config
        if dt >= cfg.silence_hard_beats:
            return 0.0
        if dt <= cfg.silence_soft_beats:
            return 1.0
        return exp(-(dt - cfg.silence_soft_beats) / cfg.silence_decay_tau)

    def _decay_reps(self, prev: HandReps, frame_beat: float) -> HandReps:
        scale = self._silence_scale(prev, frame_beat)
        if scale >= 1.0:
            return prev
        if scale <= 0.0:
            return HandReps(last_beat=prev.last_beat)
        # Soft decay: keep pitches but clear aged anchors after soft silence.
        keep_bass = (
            prev.lh_bass
            if prev.lh_bass_beat is not None
            and frame_beat - prev.lh_bass_beat < self.config.silence_hard_beats
            else None
        )
        keep_melody = (
            prev.rh_melody
            if prev.rh_melody_beat is not None
            and frame_beat - prev.rh_melody_beat < self.config.silence_hard_beats
            else None
        )
        return HandReps(
            lh=prev.lh if scale > 0.35 else None,
            rh=prev.rh if scale > 0.35 else None,
            lh_vel=prev.lh_vel * scale,
            rh_vel=prev.rh_vel * scale,
            lh_bass=keep_bass if scale > 0.2 else None,
            rh_melody=keep_melody if scale > 0.2 else None,
            last_beat=prev.last_beat,
            lh_beat=prev.lh_beat,
            rh_beat=prev.rh_beat,
            lh_bass_beat=prev.lh_bass_beat if keep_bass is not None else None,
            rh_melody_beat=prev.rh_melody_beat if keep_melody is not None else None,
        )

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
                frame_beat = frame[0].start_beat
                for i, _pst in enumerate(states[t - 1]):
                    prev = self._decay_reps(carry[t - 1][i], frame_beat)
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
        cost += self._same_hand_texture_cost(lh) + self._same_hand_texture_cost(rh)

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

    def _same_hand_texture_cost(self, pitches: list[int]) -> float:
        """One hand owning bass+melody (or a very wide span) is almost never right."""
        if len(pitches) < 2:
            return 0.0
        cfg = self.config
        lo, hi = min(pitches), max(pitches)
        span = hi - lo
        cost = 0.0
        if span >= cfg.same_hand_span_soft:
            cost += cfg.same_hand_span_weight * (span - cfg.same_hand_span_soft + 1)
        if lo <= cfg.bass_register_max and hi >= cfg.melody_register_min:
            cost += cfg.bass_melody_same_hand_weight
        # Mid harmony + melody attack in one frame also belongs on two hands.
        # Keep this below middle C so melody octave doublings (C4+C5) stay intact.
        elif lo <= 58 and hi >= cfg.melody_register_min and span >= 10:
            cost += cfg.bass_melody_same_hand_weight * 0.85
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
        frame_beat = notes[0].start_beat if notes else 0.0
        prev = self._decay_reps(prev, frame_beat)
        sticky = self._silence_scale(prev, frame_beat)
        curr = self._centroids(notes, assign)
        cost = 0.0
        prev_pitch = (prev.lh, prev.rh)
        prev_vel = (prev.lh_vel, prev.rh_vel)

        for hand, cc in ((LH, curr[LH]), (RH, curr[RH])):
            prior = prev_pitch[hand]
            if prior is not None and cc is not None:
                jump = abs(cc - prior)
                # Bass then mid-interval LH figures reverse direction on purpose;
                # do not charge full motion for that reset into the RH-LH gap.
                gap_reset = (
                    hand == LH
                    and (prev.rh_melody is not None or prev.rh is not None)
                    and prior <= cfg.bass_register_max + 4
                    and prior < cc < (prev.rh_melody if prev.rh_melody is not None else prev.rh)
                )
                motion_scale = 0.35 if gap_reset else 1.0
                cost += cfg.motion_weight * motion_scale * (jump / 12.0)
                if jump > cfg.large_jump_semitones and not gap_reset:
                    cost += cfg.motion_weight * ((jump - cfg.large_jump_semitones) / 5.0)
                predicted = prior + prev_vel[hand]
                reversing = (cc - prior) * prev_vel[hand] < 0 and abs(cc - prior) > 8
                if not reversing and not gap_reset:
                    cost += cfg.trajectory_weight * (abs(cc - predicted) / 12.0)

        for note, a in zip(notes, assign):
            my_prev = prev_pitch[a]
            other_prev = prev_pitch[1 - a]
            if my_prev is None and other_prev is not None:
                stay_jump = abs(note.pitch - other_prev)
                # Opening a silent hand is expensive if the active hand can still
                # reach this pitch. True opposite-register entries stay cheap.
                if stay_jump <= 28:
                    cost += (
                        cfg.switch_weight
                        * sticky
                        * max(0.0, 1.0 - stay_jump / 28.0)
                    )
            if prev.lh is not None and prev.rh is not None:
                pred_lh = prev.lh + prev.lh_vel
                pred_rh = prev.rh + prev.rh_vel
                lo, hi = (prev.lh, prev.rh) if prev.lh <= prev.rh else (prev.rh, prev.lh)
                # Notes between the hands fill a broken-chord gap; use last
                # pitches, not velocity extrapolation (bass→mid is a reset).
                if lo < note.pitch < hi:
                    d_lh = abs(note.pitch - prev.lh)
                    d_rh = abs(note.pitch - prev.rh)
                else:
                    d_lh = abs(note.pitch - pred_lh)
                    d_rh = abs(note.pitch - pred_rh)
                natural = LH if d_lh <= d_rh else RH
                if natural != a:
                    cost += cfg.direction_weight * (abs(d_lh - d_rh) / 8.0)
            cost += sticky * self._accompaniment_stream_cost(note, a, prev)

        nxt = self._update_reps(prev, notes, assign)
        if nxt.lh is not None and nxt.rh is not None and nxt.lh > nxt.rh + 1.0:
            # Persistent crossing is penalized more than a first crossing frame.
            persistent = prev.lh is not None and prev.rh is not None and prev.lh > prev.rh
            scale = 1.6 if persistent else 0.45
            cost += cfg.crossing_weight * scale * ((nxt.lh - nxt.rh) / 6.0)
        return cost

    def _accompaniment_stream_cost(
        self, note: MusicalEvent, hand: int, prev: HandReps
    ) -> float:
        """Keep broken-chord / waltz mid intervals on LH once a bass+melody texture exists.

        Uses register anchors so a brief mid RH theft cannot erase the texture.
        Mid notes under an active melody prefer LH, including repeats after the
        bass has already moved up into the harmony band.
        """
        cfg = self.config
        bass = prev.lh_bass if prev.lh_bass is not None else prev.lh
        melody = prev.rh_melody if prev.rh_melody is not None else prev.rh
        if bass is None or melody is None:
            return 0.0
        if melody < cfg.melody_register_min - 2:
            return 0.0
        if not (cfg.bass_register_max < note.pitch < cfg.melody_register_min):
            return 0.0
        drop = melody - note.pitch
        if drop < cfg.accomp_drop_min:
            return 0.0
        lh_ref = prev.lh if prev.lh is not None else bass
        # Already in the mid band: stay with LH rather than stealing from melody.
        if lh_ref > cfg.bass_register_max:
            if abs(note.pitch - lh_ref) > 12:
                return 0.0
            if hand == RH:
                return cfg.accomp_stream_weight * min(1.35, drop / 10.0)
            return 0.0
        rise = note.pitch - bass
        if rise < 0 or rise > cfg.accomp_rise_max:
            return 0.0
        strength = min(1.25, drop / max(rise, 1.0))
        if hand == RH:
            return cfg.accomp_stream_weight * strength
        return 0.0

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
        cfg = self.config
        frame_beat = notes[0].start_beat if notes else (prev.last_beat or 0.0)
        prev = self._decay_reps(prev, frame_beat)
        curr_lh, curr_rh = self._centroids(notes, assign)
        lh_vel = prev.lh_vel
        rh_vel = prev.rh_vel
        lh_beat = prev.lh_beat
        rh_beat = prev.rh_beat
        if curr_lh is not None and prev.lh is not None:
            lh_vel = curr_lh - prev.lh
        elif curr_lh is None:
            curr_lh = prev.lh
        if curr_lh is not None and any(a == LH for a in assign):
            lh_beat = frame_beat
        if curr_rh is not None and prev.rh is not None:
            rh_vel = curr_rh - prev.rh
        elif curr_rh is None:
            curr_rh = prev.rh
        if curr_rh is not None and any(a == RH for a in assign):
            rh_beat = frame_beat
        lh_bass = prev.lh_bass
        rh_melody = prev.rh_melody
        lh_bass_beat = prev.lh_bass_beat
        rh_melody_beat = prev.rh_melody_beat
        if curr_lh is not None and curr_lh <= cfg.bass_register_max + 4 and any(a == LH for a in assign):
            lh_bass = curr_lh
            lh_bass_beat = frame_beat
        if curr_rh is not None and any(a == RH for a in assign):
            if curr_rh >= cfg.melody_register_min - 2:
                rh_melody = curr_rh
                rh_melody_beat = frame_beat
            elif rh_melody is not None:
                prior_rh = prev.rh if prev.rh is not None else rh_melody
                # Follow a stepwise descending melody so intentional crossing
                # can complete; keep the high anchor after a sudden mid jump.
                if abs(curr_rh - prior_rh) <= 5:
                    rh_melody = curr_rh
                    rh_melody_beat = frame_beat
        return HandReps(
            lh=curr_lh,
            rh=curr_rh,
            lh_vel=lh_vel,
            rh_vel=rh_vel,
            lh_bass=lh_bass,
            rh_melody=rh_melody,
            last_beat=frame_beat,
            lh_beat=lh_beat,
            rh_beat=rh_beat,
            lh_bass_beat=lh_bass_beat,
            rh_melody_beat=rh_melody_beat,
        )

    def _note_factors(
        self,
        note: MusicalEvent,
        hand: int,
        prev: HandReps,
    ) -> dict:
        """Cost factors used by the search. Confidence remains an uncalibrated margin."""
        prior = prev.rh if hand == RH else prev.lh
        vel = prev.rh_vel if hand == RH else prev.lh_vel
        motion = 0.0
        traj = 0.0
        if prior is not None:
            motion = self.config.motion_weight * (abs(note.pitch - prior) / 12.0)
            traj = self.config.trajectory_weight * (
                abs(note.pitch - (prior + vel)) / 12.0
            )
        lh_pitches = [note.pitch] if hand == LH else []
        rh_pitches = [note.pitch] if hand == RH else []
        texture = self._same_hand_texture_cost(lh_pitches or rh_pitches)
        accomp = self._accompaniment_stream_cost(note, hand, prev)
        anchor_beat = prev.rh_melody_beat if hand == RH else prev.lh_bass_beat
        anchor_age = (
            max(0.0, note.start_beat - anchor_beat) if anchor_beat is not None else None
        )
        return {
            "register": round(self._register_cost(note.pitch, hand), 3),
            "motion": round(motion, 3),
            "trajectory": round(traj, 3),
            "role": round(self._role_cost(note, hand), 3),
            "incoming_hint": round(self._incoming_hint_cost(note, hand), 3),
            "texture": round(texture, 3),
            "accomp_stream": round(accomp, 3),
            "same_hand_span": 0,
            "anchor_age_beats": None if anchor_age is None else round(anchor_age, 3),
            "confidence_uncalibrated": True,
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
            prev = self._decay_reps(prev, frame[0].start_beat)
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
                # An isolated attack within a phrase still has the Viterbi
                # path's context. AMBIGUOUS would discard that path and make
                # staff_for_hand fall back to a middle-C split.
                isolated = len(frame) == 1 and len(frames) == 1
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


def build_hand_separator(
    mode: str | None = None,
    *,
    processor=None,
    fallback: HandSeparator | None = None,
):
    """Construct the configured piano hand splitter. Default is Viterbi."""
    from mir.pipeline_config import HandSeparatorMode, parse_hand_separator_mode

    resolved = parse_hand_separator_mode(mode)
    if resolved is HandSeparatorMode.PM2S:
        from mir.pm2s_hands import Pm2sHandSeparator

        return Pm2sHandSeparator(processor=processor, fallback=fallback)
    return HandSeparator()
