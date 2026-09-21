"""Voice assignment with stream continuity.

Simultaneous compact pitches become a chord in one voice.
Independent overlapping streams become separate voices on the same staff.
Hand, musical voice, printed lane, and musical role stay distinct: this
module only assigns a printed lane (`voice`) unless a user label is locked.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import permutations
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

        voices: list[dict] = []
        assigned: list[MusicalEvent] = []
        for item in prepared:
            locked = [
                ev
                for ev in item["events"]
                if ev.voice_assigned and ev.voice_provenance == "user_edit"
            ]
            if not locked:
                continue
            voice_id = int(locked[0].voice)
            voices.append(
                {
                    "id": voice_id,
                    "pitch": item["pitch"],
                    "end": item["end"],
                    "dur": item["dur"],
                    "role": item["role"],
                    "locked": True,
                }
            )

        for index, item in enumerate(prepared):
            locked = [
                ev
                for ev in item["events"]
                if ev.voice_assigned and ev.voice_provenance == "user_edit"
            ]
            if locked:
                voice_id = int(locked[0].voice)
                for vs in voices:
                    if vs["id"] == voice_id:
                        vs.update(
                            pitch=item["pitch"],
                            end=item["end"],
                            dur=item["dur"],
                            role=item["role"],
                        )
                        break
                leap_conf = 1.0
            else:
                onset, end, pitch, dur = item["onset"], item["end"], item["pitch"], item["dur"]
                look = prepared[index + 1 : index + 1 + max(0, int(cfg.lookahead_clusters))]
                best_i = None
                best_cost = float("inf")
                for i, vs in enumerate(voices):
                    overlap = vs["end"] - onset
                    if overlap > cfg.overlap_grace_beats:
                        continue
                    leap = abs(vs["pitch"] - pitch)
                    gap = max(0.0, onset - vs["end"])
                    cost = leap * 0.9
                    cost += 1.4 * max(0.0, gap - 0.75)
                    cost += 0.35 * abs(vs["dur"] - dur)
                    if leap > cfg.max_leap:
                        cost += 40.0
                    if vs.get("role") and item["role"] and vs["role"] != item["role"]:
                        cost += 4.0
                    if vs.get("locked"):
                        cost += 8.0
                    cost += self._lookahead_cost(vs, item, look, cfg)
                    if cost < best_cost:
                        best_cost = cost
                        best_i = i
                create_new = (
                    best_i is None
                    or best_cost > cfg.new_voice_cost
                    or len(voices) == 0
                )
                if create_new and best_i is not None and best_cost <= cfg.new_voice_cost:
                    create_new = False
                if create_new:
                    over_policy = len(voices) >= cfg.max_voices_per_hand
                    if over_policy and best_i is not None and best_cost <= cfg.new_voice_cost + 12:
                        voice_id = voices[best_i]["id"]
                        voices[best_i] = {
                            "id": voice_id,
                            "pitch": pitch,
                            "end": end,
                            "dur": dur,
                            "role": item["role"],
                        }
                    else:
                        if over_policy:
                            self.last_diagnostics.append(
                                {
                                    "kind": "voice_limit_exceeded",
                                    "hand": hand.value if hasattr(hand, "value") else str(hand),
                                    "policy_limit": cfg.max_voices_per_hand,
                                    "required_lanes": len({vs["id"] for vs in voices}) + 1,
                                    "onset": onset,
                                    "action": "extra_printed_lane",
                                }
                            )
                        used_ids = {vs["id"] for vs in voices}
                        voice_id = 0
                        while voice_id in used_ids:
                            voice_id += 1
                        voices.append(
                            {
                                "id": voice_id,
                                "pitch": pitch,
                                "end": end,
                                "dur": dur,
                                "role": item["role"],
                            }
                        )
                else:
                    voice_id = voices[best_i]["id"]
                    voices[best_i] = {
                        "id": voice_id,
                        "pitch": pitch,
                        "end": end,
                        "dur": dur,
                        "role": item["role"],
                    }
                leap_conf = 1.0
                if best_i is not None:
                    leap_conf = max(0.35, 1.0 - best_cost / 40.0)

            for ev in item["events"]:
                if ev.voice_assigned and ev.voice_provenance == "user_edit":
                    assigned.append(ev)
                    continue
                assigned.append(
                    copy_event(
                        ev,
                        voice=voice_id,
                        voice_confidence=round(leap_conf, 3),
                        voice_assigned=True,
                    )
                )
        return assigned

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
        if (
            len(ordered) == 2
            and ordered[1].pitch - ordered[0].pitch >= 6
            and (
                not self.config.prefer_simple_chords
                or abs(ordered[1].duration_beats - ordered[0].duration_beats) > 0.20
                or (
                    ordered[0].role
                    and ordered[1].role
                    and ordered[0].role != ordered[1].role
                )
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


def permutation_invariant_accuracy(predicted: list[int], truth: list[int]) -> float:
    """Best accuracy after remapping predicted lane IDs onto truth IDs.

    This is a match rate, not a calibrated probability.
    """
    if not predicted or len(predicted) != len(truth):
        return 0.0
    truth_ids = sorted(set(truth))
    pred_ids = sorted(set(predicted))
    if not truth_ids:
        return 0.0
    best = 0.0
    take = min(len(pred_ids), len(truth_ids))
    for mapped in permutations(truth_ids, take):
        mapping = dict(zip(pred_ids, mapped))
        hits = sum(1 for pred, expected in zip(predicted, truth) if mapping.get(pred) == expected)
        best = max(best, hits / len(truth))
    return best


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
