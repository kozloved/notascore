"""Build an explicit NotationPlan from structured musical events."""

from __future__ import annotations

from collections import defaultdict

from mir.meter import MeterEstimator, meter_from_time_signature
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
from mir.quantizer import MeasureQuantizer, VOICE_SUM_TOLERANCE
from mir.types import Hand, InstrumentKind, MusicalEvent, ScoreMeta
from notation_engine.meter import estimate_key

CHORD_DURATION_RATIO = 0.5
REST_CANDIDATES = (
    4.0,
    3.0,
    2.0,
    1.5,
    1.0,
    0.75,
    2.0 / 3.0,
    0.5,
    0.375,
    1.0 / 3.0,
    0.25,
    0.125,
)


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
        meter = self._resolve_meter(events, meta, structure)
        quantized, decisions = self.quantizer.quantize(events, meter)
        bpm = (meta.display_tempo_bpm if meta else None) or int(fallback_bpm)
        key_name = self._resolve_key(quantized, meta, structure)

        pianoish = self._use_grand_staff(quantized, structure, meta)
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

        extra = {"meter_confidence": meter.confidence}
        if meta and meta.extra:
            if meta.extra.get("meter_decision"):
                extra["meter_decision"] = meta.extra["meter_decision"]
            if meta.extra.get("meter_source"):
                extra["meter_source"] = meta.extra["meter_source"]
        plan = NotationPlan(
            tempo_bpm=int(bpm),
            time_signature=meter.time_signature,
            key_signature=key_name,
            measures=measures,
            extra=extra,
        )
        return plan, decisions

    def _resolve_meter(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta | None,
        structure: MusicalStructure | None,
    ) -> MeterHypothesis:
        """Use a canonical MeterDecision when present.

        madmom grouping strings are never treated as an unquestioned hint.
        MIDI file meters and explicit test hints remain authoritative.
        """
        extra = dict(meta.extra or {}) if meta else {}
        source = str(extra.get("meter_source") or "")
        hint = meta.time_sig_hint if meta else None
        selected = structure.selected_meter if structure else None

        if source == "madmom":
            if selected:
                return selected
            return self.meter_estimator.select(events)

        if source == "meter_decision" and selected:
            if not hint or hint == selected.time_signature:
                return selected
            return meter_from_time_signature(hint, source="meta_time_sig_hint")

        if hint:
            if selected and selected.time_signature == hint:
                return selected
            if structure:
                for hyp in structure.meter_hypotheses:
                    if hyp.time_signature == hint:
                        return hyp
            return meter_from_time_signature(hint, source="meta_time_sig_hint")
        if selected:
            return selected
        return self.meter_estimator.select(events)

    def _resolve_key(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta | None,
        structure: MusicalStructure | None,
    ) -> str:
        if meta and meta.key_hint:
            return meta.key_hint
        if structure and structure.selected_key:
            return structure.selected_key.name
        return estimate_key(events) or "C"

    def _use_grand_staff(
        self,
        events: list[MusicalEvent],
        structure: MusicalStructure | None,
        meta: ScoreMeta | None = None,
    ) -> bool:
        hands = {e.hand for e in events}
        if Hand.LEFT in hands or Hand.RIGHT in hands:
            return True
        if structure and structure.instrument == InstrumentKind.PIANO:
            return True
        pred = meta.instrument_prediction if meta else None
        if pred is not None and pred.instrument == InstrumentKind.PIANO:
            return True
        for ev in events:
            if ev.instrument == InstrumentKind.PIANO:
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
            dur = local_end - local_start
            if dur <= 1e-8:
                continue
            tie = None
            if ev.start_beat < start - 1e-8 and ev_end > end + 1e-8:
                tie = "continue"
            elif ev.start_beat < start - 1e-8:
                tie = "stop"
            elif ev_end > end + 1e-8:
                tie = "start"
            inside.append((ev, local_start, dur, tie))

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
                        elements=self._fill_voice(items, mql, voice_id=vid),
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

    def _fill_voice(self, items: list, mql: float, voice_id: int = 0) -> list:
        if not items:
            return [PlannedRest(start_q=0.0, duration_q=mql, voice=voice_id)]

        items = sorted(items, key=lambda it: (it[1], it[0].pitch))
        chords: list[list] = []
        for item in items:
            if chords and self._same_chord(chords[-1][0], item):
                chords[-1].append(item)
            else:
                chords.append([item])

        elements: list = []
        cursor = 0.0
        voice_id = items[0][0].voice
        for group in chords:
            start = group[0][1]
            dur = max(it[2] for it in group)
            if start < cursor - 1e-8:
                # Same-onset leftovers with incompatible duration: fold into the
                # previous chord rather than overlapping the voice timeline.
                prev = next(
                    (
                        el
                        for el in reversed(elements)
                        if isinstance(el, PlannedNote)
                    ),
                    None,
                )
                if prev is not None and abs(prev.start_q - start) < 1e-6:
                    extra = sorted({it[0].pitch for it in group})
                    prev.pitches = sorted(set(prev.pitches) | set(extra))
                    prev.duration_q = max(prev.duration_q, dur)
                    cursor = max(cursor, start + prev.duration_q)
                    continue
                start = cursor
            if start > cursor + 1e-8:
                gap = start - cursor
                elements.extend(self._rests(cursor, gap, voice_id))
                cursor = start
            dur = min(dur, max(0.0, mql - start))
            if dur <= 1e-8:
                continue
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

        self._assert_sum(elements, mql, voice_id)
        return elements

    def _same_chord(self, seed: tuple, item: tuple) -> bool:
        seed_ev, seed_start, seed_dur, _ = seed
        ev, start, dur, _ = item
        if ev.voice != seed_ev.voice:
            return False
        if staff_for_hand(ev.hand, ev.pitch) != staff_for_hand(seed_ev.hand, seed_ev.pitch):
            return False
        if abs(start - seed_start) > 1e-6:
            return False
        return self._compatible_duration(seed_dur, dur)

    @staticmethod
    def _compatible_duration(a: float, b: float) -> bool:
        short, long = sorted((a, b))
        if long <= 1e-9:
            return True
        return short >= long * CHORD_DURATION_RATIO - 1e-9

    def _rests(self, start: float, duration: float, voice: int) -> list[PlannedRest]:
        parts: list[PlannedRest] = []
        remaining = duration
        cursor = start
        if remaining <= 1e-8:
            return parts
        for d in REST_CANDIDATES:
            while remaining >= d - 1e-9:
                parts.append(PlannedRest(start_q=cursor, duration_q=d, voice=voice))
                cursor += d
                remaining -= d
        if remaining > 1e-6:
            parts.append(PlannedRest(start_q=cursor, duration_q=remaining, voice=voice))
        return parts

    def _assert_sum(self, elements: list, mql: float, voice_id: int = 0) -> None:
        self._repair_sum(elements, mql, voice_id)
        total = sum(getattr(el, "duration_q", 0.0) for el in elements)
        if abs(total - mql) > VOICE_SUM_TOLERANCE:
            raise ValueError(
                f"voice {voice_id} elements sum to {total:.4f}, "
                f"expected measure duration {mql:.4f}"
            )

    def _repair_sum(self, elements: list, mql: float, voice_id: int) -> None:
        if not elements:
            elements.append(PlannedRest(start_q=0.0, duration_q=mql, voice=voice_id))
            return
        total = sum(el.duration_q for el in elements)
        if abs(total - mql) <= 1e-6:
            return
        if total > mql:
            extra = total - mql
            for el in reversed(elements):
                if extra <= 1e-9:
                    break
                if isinstance(el, PlannedRest):
                    shrink = min(el.duration_q, extra)
                    el.duration_q -= shrink
                    extra -= shrink
                elif el.duration_q > extra:
                    el.duration_q -= extra
                    extra = 0.0
            elements[:] = [el for el in elements if el.duration_q > 1e-8]
            return
        gap = mql - total
        last = elements[-1]
        last_end = last.start_q + last.duration_q
        if isinstance(last, PlannedRest):
            last.duration_q += gap
        else:
            elements.extend(self._rests(last_end, gap, voice_id))
