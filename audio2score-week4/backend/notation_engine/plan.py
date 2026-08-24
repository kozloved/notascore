"""Build an explicit NotationPlan from structured musical events."""

from __future__ import annotations

from collections import defaultdict

from mir.meter import MeterEstimator
from mir.models import (
    MeterHypothesis,
    MusicalStructure,
    NotationPlan,
    PlannedMeasure,
    PlannedNote,
    PlannedRest,
    PlannedStaff,
    PlannedVoice,
    staff_for_hand,
)
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent, ScoreMeta


class NotationPlanner:
    """Decide measures, staves, voices, durations, rests, ties, clefs."""

    def __init__(self):
        self.meter_estimator = MeterEstimator()
        self.quantizer = MeasureQuantizer()

    def build(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta | None = None,
        structure: MusicalStructure | None = None,
        fallback_bpm: float = 120.0,
    ) -> tuple[NotationPlan, list[dict]]:
        if structure and structure.selected_meter:
            meter = structure.selected_meter
        else:
            meter = self.meter_estimator.select(events)

        quantized, decisions = self.quantizer.quantize(events, meter)
        bpm = (meta.display_tempo_bpm if meta else None) or int(fallback_bpm)
        key_name = "C"
        if structure and structure.selected_key:
            key_name = structure.selected_key.name

        pianoish = self._use_grand_staff(quantized, structure)
        end_beat = 0.0
        if quantized:
            end_beat = max(e.start_beat + e.duration_beats for e in quantized)
        n_measures = max(1, int((end_beat + 1e-6) // meter.measure_quarter_length) + 1)
        # If music ends exactly on a boundary, don't add an extra empty bar.
        if quantized and abs(end_beat % meter.measure_quarter_length) < 1e-6:
            n_measures = max(1, int(round(end_beat / meter.measure_quarter_length)))

        measures: list[PlannedMeasure] = []
        for i in range(n_measures):
            start = i * meter.measure_quarter_length
            measures.append(
                self._build_measure(
                    number=i + 1,
                    start=start,
                    meter=meter,
                    events=quantized,
                    key_name=key_name if i == 0 else None,
                    pianoish=pianoish,
                )
            )

        plan = NotationPlan(
            tempo_bpm=int(bpm),
            time_signature=meter.time_signature,
            key_signature=key_name,
            measures=measures,
            extra={"meter_confidence": meter.confidence},
        )
        return plan, decisions

    def _use_grand_staff(
        self, events: list[MusicalEvent], structure: MusicalStructure | None
    ) -> bool:
        hands = {e.hand for e in events}
        if Hand.LEFT in hands or Hand.RIGHT in hands:
            return True
        if structure and structure.instrument.value == "piano":
            return True
        return False

    def _build_measure(
        self,
        number: int,
        start: float,
        meter: MeterHypothesis,
        events: list[MusicalEvent],
        key_name: str | None,
        pianoish: bool,
    ) -> PlannedMeasure:
        mql = meter.measure_quarter_length
        end = start + mql
        inside: list[tuple[MusicalEvent, float, float, str | None]] = []
        for ev in events:
            ev_end = ev.start_beat + ev.duration_beats
            if ev_end <= start + 1e-8 or ev.start_beat >= end - 1e-8:
                continue
            local_start = max(0.0, ev.start_beat - start)
            local_end = min(mql, ev_end - start)
            tie = None
            if ev.start_beat < start - 1e-8 and ev_end > end + 1e-8:
                tie = "continue"
            elif ev.start_beat < start - 1e-8:
                tie = "stop"
            elif ev_end > end + 1e-8:
                tie = "start"
            inside.append((ev, local_start, max(0.125, local_end - local_start), tie))

        staff_ids = [0, 1] if pianoish else [0]
        staves: list[PlannedStaff] = []
        for sid in staff_ids:
            staff_events = [
                item
                for item in inside
                if staff_for_hand(item[0].hand, item[0].pitch) == sid
            ]
            voices_map: dict[int, list] = defaultdict(list)
            for item in staff_events:
                voices_map[item[0].voice].append(item)
            if not voices_map:
                voices_map[0] = []

            planned_voices = []
            for vid, items in sorted(voices_map.items()):
                planned_voices.append(
                    PlannedVoice(
                        voice_id=vid,
                        elements=self._fill_voice(items, mql),
                    )
                )
            staves.append(
                PlannedStaff(
                    staff_id=sid,
                    clef=self._clef_for(sid, staff_events),
                    name="Right Hand" if sid == 0 else "Left Hand",
                    voices=planned_voices,
                )
            )

        return PlannedMeasure(
            number=number,
            start_beat=start,
            duration_beats=mql,
            time_signature=meter.time_signature,
            key_signature=key_name,
            staves=staves,
        )

    def _clef_for(self, staff_id: int, items: list) -> str:
        if not items:
            return "treble" if staff_id == 0 else "bass"
        pitches = [it[0].pitch for it in items]
        median = sorted(pitches)[len(pitches) // 2]
        if staff_id == 0:
            return "bass" if median < 53 else "treble"
        return "treble" if median > 67 else "bass"

    def _fill_voice(self, items: list, mql: float) -> list:
        if not items:
            return [PlannedRest(start_q=0.0, duration_q=mql, voice=0)]

        # Chord-group same onset + same duration in this voice.
        items = sorted(items, key=lambda it: (it[1], it[0].pitch))
        chords: list[list] = []
        for item in items:
            if (
                chords
                and abs(chords[-1][0][1] - item[1]) < 1e-6
                and abs(chords[-1][0][2] - item[2]) < 1e-6
            ):
                chords[-1].append(item)
            else:
                chords.append([item])

        elements: list = []
        cursor = 0.0
        voice_id = items[0][0].voice
        for group in chords:
            start = group[0][1]
            dur = group[0][2]
            if start > cursor + 1e-8:
                gap = start - cursor
                elements.extend(self._rests(cursor, gap, voice_id))
                cursor = start
            pitches = sorted({it[0].pitch for it in group})
            ties = {it[3] for it in group if it[3]}
            tie = None
            if "continue" in ties:
                tie = "continue"
            elif "start" in ties and "stop" in ties:
                tie = "continue"
            elif "start" in ties:
                tie = "start"
            elif "stop" in ties:
                tie = "stop"
            arts = [it[0].articulation for it in group if it[0].articulation]
            dyns = [it[0].dynamic for it in group if it[0].dynamic]
            elements.append(
                PlannedNote(
                    pitches=pitches,
                    start_q=start,
                    duration_q=dur,
                    voice=voice_id,
                    velocity=max(it[0].velocity for it in group),
                    tie=tie,
                    event_ids=[it[0].note_id for it in group if it[0].note_id],
                    articulations=arts[:1],
                    dynamic=dyns[0] if dyns else None,
                )
            )
            cursor = max(cursor, start + dur)

        if cursor < mql - 1e-8:
            elements.extend(self._rests(cursor, mql - cursor, voice_id))

        self._assert_sum(elements, mql)
        return elements

    def _rests(self, start: float, duration: float, voice: int) -> list[PlannedRest]:
        parts = []
        remaining = duration
        cursor = start
        for d in (4.0, 2.0, 1.0, 0.5, 0.25, 0.125):
            while remaining >= d - 1e-9:
                parts.append(PlannedRest(start_q=cursor, duration_q=d, voice=voice))
                cursor += d
                remaining -= d
        if remaining > 1e-6:
            parts.append(
                PlannedRest(start_q=cursor, duration_q=max(0.125, remaining), voice=voice)
            )
        return parts

    def _assert_sum(self, elements: list, mql: float) -> None:
        total = sum(
            getattr(el, "duration_q", 0.0) for el in elements
        )
        # Tiny float slop only; planner may slightly overfill from rest rounding.
        if total > mql + 0.13:
            # Trim last rest if needed.
            for el in reversed(elements):
                if isinstance(el, PlannedRest) and total > mql:
                    extra = total - mql
                    if el.duration_q > extra:
                        el.duration_q -= extra
                        total -= extra
                        break
