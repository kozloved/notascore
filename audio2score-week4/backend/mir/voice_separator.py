"""Voice assignment with stream continuity.

Simultaneous compact pitches become a chord in one voice.
Independent overlapping streams become separate voices on the same staff.
"""

from __future__ import annotations

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


class VoiceSeparator:
    def __init__(self, config: VoiceSeparatorConfig | None = None):
        self.config = config or VoiceSeparatorConfig()

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        if not events:
            return []

        by_hand: dict[Hand, list[MusicalEvent]] = {}
        for ev in events:
            by_hand.setdefault(ev.hand, []).append(ev)

        result: list[MusicalEvent] = []
        for hand, group in by_hand.items():
            result.extend(self._separate_hand(group))
        return sorted(
            result,
            key=lambda e: (e.hand.value, e.start_beat, e.pitch),
        )

    def _separate_hand(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        cfg = self.config
        ordered = sorted(events, key=lambda e: (e.start_beat, e.pitch))
        clusters = self._cluster(ordered)
        voices: list[dict] = []
        assigned: list[MusicalEvent] = []

        for cluster in clusters:
            groups = self._split_cluster(cluster)
            for group in groups:
                onset = min(e.start_beat for e in group)
                end = max(e.start_beat + e.duration_beats for e in group)
                pitch = mean(e.pitch for e in group)
                dur = mean(e.duration_beats for e in group)
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
                    if vs.get("role") and group[0].role and vs["role"] != group[0].role:
                        cost += 4.0
                    if cost < best_cost:
                        best_cost = cost
                        best_i = i
                if (
                    best_i is None
                    or best_cost > cfg.new_voice_cost
                    or len(voices) == 0
                ):
                    if best_i is not None and best_cost <= cfg.new_voice_cost:
                        voice_id = voices[best_i]["id"]
                        voices[best_i] = {
                            "id": voice_id,
                            "pitch": pitch,
                            "end": end,
                            "dur": dur,
                            "role": group[0].role,
                        }
                    else:
                        if len(voices) >= cfg.max_voices_per_hand and best_i is not None:
                            voice_id = voices[best_i]["id"]
                            voices[best_i] = {
                                "id": voice_id,
                                "pitch": pitch,
                                "end": end,
                                "dur": dur,
                                "role": group[0].role,
                            }
                        else:
                            voice_id = len(voices)
                            voices.append(
                                {
                                    "id": voice_id,
                                    "pitch": pitch,
                                    "end": end,
                                    "dur": dur,
                                    "role": group[0].role,
                                }
                            )
                else:
                    voice_id = voices[best_i]["id"]
                    voices[best_i] = {
                        "id": voice_id,
                        "pitch": pitch,
                        "end": end,
                        "dur": dur,
                        "role": group[0].role,
                    }

                leap_conf = 1.0
                if best_i is not None:
                    leap_conf = max(0.35, 1.0 - best_cost / 40.0)
                for ev in group:
                    assigned.append(
                        copy_event(
                            ev,
                            voice=voice_id,
                            voice_confidence=round(leap_conf, 3),
                        )
                    )
        return assigned

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

    def _split_cluster(
        self, cluster: list[MusicalEvent]
    ) -> list[list[MusicalEvent]]:
        if len(cluster) <= 1:
            return [cluster]
        ordered = sorted(cluster, key=lambda e: e.pitch)
        span = ordered[-1].pitch - ordered[0].pitch
        if span <= self.config.max_chord_span:
            durs = [e.duration_beats for e in ordered]
            if max(durs) - min(durs) < 0.85 or span <= 7:
                return [ordered]
        groups: list[list[MusicalEvent]] = [[ordered[0]]]
        for ev in ordered[1:]:
            prev = groups[-1][-1]
            if ev.pitch - prev.pitch >= self.config.split_gap:
                groups.append([ev])
            else:
                groups[-1].append(ev)
        return groups
