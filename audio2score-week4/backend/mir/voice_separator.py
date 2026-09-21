"""Voice assignment with stream continuity.

Simultaneous compact pitches become a chord in one voice.
Independent overlapping streams become separate voices on the same staff.

These stay distinct:
- Musical line identity (``musical_voice``)
- Hand / staff assignment (``hand``)
- Printed collision-free lane (``voice`` after lane allocation)
- Musical role (``role``, never an inference input unless opted in)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean

from mir.types import Hand, MusicalEvent, copy_event


@dataclass
class VoiceSeparatorConfig:
    chord_window_beats: float = 0.07
    max_chord_span: int = 14
    split_gap: int = 8
    max_leap: int = 16
    max_voices_per_hand: int = 4
    overlap_grace_beats: float = 0.04
    new_voice_cost: float = 18.0
    prefer_simple_chords: bool = False
    lookahead_clusters: int = 2
    mixed_release_beats: float = 0.85
    # Role labels are a separate musical concept. Keep them out of assignment
    # unless a caller is explicitly evaluating supplied-hint behavior.
    use_role_hints: bool = False


class VoiceSeparator:
    def __init__(self, config: VoiceSeparatorConfig | None = None):
        self.config = config or VoiceSeparatorConfig()
        self.last_diagnostics: list[dict] = []

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        self.last_diagnostics = []
        if not events:
            return []

        by_hand: dict[Hand, list[MusicalEvent]] = {}
        for ev in events:
            by_hand.setdefault(ev.hand, []).append(ev)

        result: list[MusicalEvent] = []
        for hand, group in by_hand.items():
            result.extend(self._separate_hand(group, hand))
        return sorted(
            result,
            key=lambda e: (e.hand.value, e.start_beat, e.pitch),
        )

    def _separate_hand(self, events: list[MusicalEvent], hand: Hand) -> list[MusicalEvent]:
        cfg = self.config
        ordered = sorted(events, key=lambda e: (e.start_beat, e.pitch))
        clusters = self._cluster(ordered)
        prepared: list[dict] = []
        for cluster in clusters:
            for group in self._split_cluster(cluster):
                prepared.append(
                    {
                        "events": group,
                        "onset": min(e.start_beat for e in group),
                        "end": max(e.start_beat + e.duration_beats for e in group),
                        "pitch": mean(e.pitch for e in group),
                        "dur": mean(e.duration_beats for e in group),
                        "role": group[0].role,
                    }
                )

        reserved: dict[int, list[dict]] = {}
        for item in prepared:
            locked = _locked_events(item)
            if not locked:
                continue
            reserved.setdefault(int(locked[0].voice), []).append(item)

        voices: dict[int, dict] = {}
        assigned: list[MusicalEvent] = []
        for index, item in enumerate(prepared):
            locked = _locked_events(item)
            onset, end, pitch, dur = item["onset"], item["end"], item["pitch"], item["dur"]
            look = prepared[index + 1 : index + 1 + max(0, int(cfg.lookahead_clusters))]
            if locked:
                voice_id = int(locked[0].voice)
                voices[voice_id] = {
                    "id": voice_id,
                    "pitch": pitch,
                    "end": end,
                    "dur": dur,
                    "role": item["role"],
                    "locked": True,
                }
                leap_conf = 1.0
                provenance = "user_edit"
            else:
                voice_id, leap_conf = self._choose_voice(
                    item, voices, reserved, look, cfg, hand
                )
                provenance = "inferred"
            for ev in item["events"]:
                if ev.voice_assigned and ev.voice_provenance == "user_edit":
                    assigned.append(
                        copy_event(
                            ev,
                            musical_voice=int(ev.voice),
                            voice_provenance="user_edit",
                        )
                    )
                    continue
                assigned.append(
                    copy_event(
                        ev,
                        voice=voice_id,
                        musical_voice=voice_id,
                        voice_confidence=round(leap_conf, 3),
                        voice_assigned=True,
                        voice_provenance=provenance,
                    )
                )
        return assigned

    def _choose_voice(self, item, voices, reserved, look, cfg, hand) -> tuple[int, float]:
        onset, end, pitch, dur = item["onset"], item["end"], item["pitch"], item["dur"]
        candidates: list[tuple[float, int]] = []

        def _free(vs) -> bool:
            return vs["end"] - onset <= cfg.overlap_grace_beats

        def _overlaps_future_lock(voice_id) -> bool:
            for lock in reserved.get(voice_id, ()):
                if lock is item:
                    continue
                if lock["onset"] >= end - cfg.overlap_grace_beats:
                    continue
                if lock["end"] <= onset + cfg.overlap_grace_beats:
                    continue
                return True
            return False

        for vs in voices.values():
            if not _free(vs):
                continue
            if _overlaps_future_lock(vs["id"]):
                continue
            leap = abs(vs["pitch"] - pitch)
            gap = max(0.0, onset - vs["end"])
            cost = leap * 0.9
            cost += 1.4 * max(0.0, gap - 0.75)
            cost += 0.35 * abs(vs["dur"] - dur)
            if leap > cfg.max_leap:
                cost += 40.0
            if cfg.use_role_hints and vs.get("role") and item["role"] and vs["role"] != item["role"]:
                cost += 4.0
            if vs.get("locked"):
                cost += 2.0
            cost += self._lookahead_cost(vs, item, look, cfg)
            candidates.append((cost, vs["id"]))

        for voice_id, locks in reserved.items():
            if voice_id in voices and not _free(voices[voice_id]):
                continue
            if _overlaps_future_lock(voice_id):
                continue
            future = [lock for lock in locks if lock["onset"] > onset + 1e-9]
            if not future:
                continue
            nearest = future[0]
            leap = abs(nearest["pitch"] - pitch)
            gap = max(0.0, nearest["onset"] - end)
            cost = leap * 0.9 + 1.4 * max(0.0, gap - 0.75)
            if leap == 0:
                cost -= 10.0
            candidates.append((cost, voice_id))

        best = min(candidates, key=lambda row: row[0]) if candidates else None
        create_new = best is None or best[0] > cfg.new_voice_cost
        if create_new and best is not None and best[0] <= cfg.new_voice_cost:
            create_new = False
        if not create_new and best is not None:
            voice_id = best[1]
        else:
            over_policy = len(voices) >= cfg.max_voices_per_hand
            if over_policy and best is not None and best[0] <= cfg.new_voice_cost + 12:
                voice_id = best[1]
            else:
                if over_policy:
                    self.last_diagnostics.append(
                        {
                            "kind": "voice_limit_exceeded",
                            "hand": hand.value if hasattr(hand, "value") else str(hand),
                            "policy_limit": cfg.max_voices_per_hand,
                            "required_lanes": len(voices) + 1,
                            "onset": onset,
                            "action": "extra_printed_lane",
                        }
                    )
                used_ids = set(voices) | set(reserved)
                voice_id = 0
                while voice_id in used_ids:
                    voice_id += 1
        voices[voice_id] = {
            "id": voice_id,
            "pitch": pitch,
            "end": end,
            "dur": dur,
            "role": item["role"],
            "locked": bool(voice_id in reserved),
        }
        leap_conf = 1.0
        if best is not None:
            leap_conf = max(0.35, 1.0 - best[0] / 40.0)
        return voice_id, leap_conf

    def _lookahead_cost(self, vs, item, look, cfg) -> float:
        """Penalize stealing a lane that later groups need for a closer pitch."""
        extra = 0.0
        for nxt in look[: cfg.lookahead_clusters]:
            if nxt["onset"] < item["end"] - cfg.overlap_grace_beats:
                continue
            if nxt["onset"] < vs["end"] - cfg.overlap_grace_beats:
                continue
            leap_if_taken = abs(item["pitch"] - nxt["pitch"])
            leap_if_left = abs(vs["pitch"] - nxt["pitch"])
            if leap_if_left + 3 < leap_if_taken:
                extra += 0.45 * (leap_if_taken - leap_if_left)
        return extra

    def _cluster(self, events: list[MusicalEvent]) -> list[list[MusicalEvent]]:
        clusters: list[list[MusicalEvent]] = []
        for ev in events:
            if (
                clusters
                and ev.start_beat - clusters[-1][0].start_beat
                <= self.config.chord_window_beats
            ):
                clusters[-1].append(ev)
            else:
                clusters.append([ev])
        return clusters

    def _split_cluster(self, cluster: list[MusicalEvent]) -> list[list[MusicalEvent]]:
        if len(cluster) <= 1:
            return [cluster]
        ordered = sorted(cluster, key=lambda e: e.pitch)
        span = ordered[-1].pitch - ordered[0].pitch
        role_split = (
            self.config.use_role_hints
            and ordered[0].role
            and ordered[1].role
            and ordered[0].role != ordered[1].role
        )
        if (
            len(ordered) == 2
            and ordered[1].pitch - ordered[0].pitch >= 6
            and (
                not self.config.prefer_simple_chords
                or abs(ordered[1].duration_beats - ordered[0].duration_beats) > 0.20
                or role_split
            )
        ):
            return [[ordered[0]], [ordered[1]]]
        durs = [e.duration_beats for e in ordered]
        spread = max(durs) - min(durs)
        if span <= self.config.max_chord_span and spread < self.config.mixed_release_beats:
            return [ordered]
        if spread >= self.config.mixed_release_beats:
            short_d = min(durs)
            holds = [
                e
                for e in ordered
                if e.duration_beats - short_d >= self.config.mixed_release_beats
            ]
            body = [e for e in ordered if e not in holds]
            parts: list[list[MusicalEvent]] = []
            if body:
                parts.extend(self._split_by_gap(body))
            parts.extend([[hold] for hold in holds])
            if parts:
                return parts
        return self._split_by_gap(ordered)

    def _split_by_gap(self, ordered: list[MusicalEvent]) -> list[list[MusicalEvent]]:
        groups: list[list[MusicalEvent]] = [[ordered[0]]]
        for ev in ordered[1:]:
            prev = groups[-1][-1]
            if ev.pitch - prev.pitch >= self.config.split_gap:
                groups.append([ev])
            else:
                groups[-1].append(ev)
        return groups


def _locked_events(item) -> list[MusicalEvent]:
    return [
        ev
        for ev in item["events"]
        if ev.voice_assigned and ev.voice_provenance == "user_edit"
    ]


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment. ``cost`` is square. Returns col index per row."""
    n = len(cost)
    if n == 0:
        return []
    inf = 1e15
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = [0] * n
    for j in range(1, n + 1):
        if p[j] != 0:
            assignment[p[j] - 1] = j - 1
    return assignment


def permutation_invariant_accuracy(predicted: list[int], truth: list[int]) -> float:
    """Best accuracy after an optimal remapping of predicted labels onto truth.

    Extra predicted labels may remain unmatched. This is a match rate, not a
    calibrated probability. Empty vs empty is 1.0; unequal lengths are 0.0.
    """
    if predicted is None or truth is None:
        return 0.0
    if len(predicted) != len(truth):
        return 0.0
    if not predicted:
        return 1.0
    pred_ids = list(dict.fromkeys(predicted))
    truth_ids = list(dict.fromkeys(truth))
    dim = max(len(pred_ids), len(truth_ids))
    counts = [[0] * dim for _ in range(dim)]
    pred_index = {label: i for i, label in enumerate(pred_ids)}
    truth_index = {label: i for i, label in enumerate(truth_ids)}
    for pred, expected in zip(predicted, truth):
        counts[pred_index[pred]][truth_index[expected]] += 1
    n = float(len(truth))
    cost = [[n - counts[i][j] for j in range(dim)] for i in range(dim)]
    assignment = _hungarian(cost)
    hits = 0
    for i, j in enumerate(assignment):
        if i < len(pred_ids) and j < len(truth_ids):
            hits += counts[i][j]
    return hits / n


def fragmentation_count(
    events: list[MusicalEvent], *, truth_attr: str, pred_attr: str = "voice"
) -> int:
    """Count predicted-lane changes along each true musical line."""
    by_line: dict[object, list] = defaultdict(list)
    for ev in sorted(events, key=lambda e: (e.start_beat, e.pitch, e.note_id or "")):
        label = getattr(ev, truth_attr, None)
        if label is None:
            continue
        by_line[label].append(getattr(ev, pred_attr))
    switches = 0
    for seq in by_line.values():
        switches += sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    return switches


def extra_printed_lanes(predicted: list[int], truth: list[int]) -> int:
    """How many predicted lanes exceed the true line count."""
    return max(0, len(set(predicted)) - len(set(truth)))
