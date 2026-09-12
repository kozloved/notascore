"""Build an explicit NotationPlan from structured musical events."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

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
from mir.job import QuantizationResult
from mir.quantizer import (
    MeasureQuantizer,
    VOICE_SUM_TOLERANCE,
    duration_pieces,
    tie_chain,
)
from mir.pipeline_config import (
    QuantizationMode,
    parse_quantization_mode,
    quantization_spells_writable,
)
from mir.types import Hand, InstrumentKind, MusicalEvent, ScoreMeta
from notation_engine.meter import estimate_key

# Near-equal durations only. A quarter + a half at the same onset must not
# become one chord with the longer duration (that destroys voice timing).
CHORD_DURATION_RATIO = 0.85
# Gaps smaller than a 64th rest are absorbed instead of spelled as clutter.
REST_MIN_QL = 0.0625
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
TIMELINE_TOL = 1e-6


def log_notation_invariant(kind: str, **fields) -> None:
    """Compact invariant log. Never dump whole music21/plan objects."""
    parts = [f"{key}={fields[key]}" for key in fields if fields[key] is not None]
    print("[NotationInvariant] " + kind + ((" " + " ".join(parts)) if parts else ""))


def validate_voice_timeline(elements, measure_length: float) -> list[dict]:
    """Return issues for a single-voice measure timeline.

    Validation is independent of input list order. Same-voice overlap is an
    error; gaps, overflow, and non-positive durations are also reported.
    """
    mql = float(measure_length)
    issues: list[dict] = []
    ordered = sorted(
        enumerate(elements or []),
        key=lambda item: (
            float(getattr(item[1], "start_q", 0.0) or 0.0),
            float(getattr(item[1], "duration_q", 0.0) or 0.0),
            item[0],
        ),
    )
    cursor = 0.0
    total = 0.0
    prev_end = None
    for _, el in ordered:
        kind = type(el).__name__
        start = float(getattr(el, "start_q", 0.0) or 0.0)
        dur = float(getattr(el, "duration_q", 0.0) or 0.0)
        end = start + dur
        pitches = getattr(el, "pitches", None)
        event_ids = getattr(el, "event_ids", None)
        base = {
            "element": kind,
            "start": start,
            "duration": dur,
            "end": end,
            "measure_length": mql,
            "event_ids": list(event_ids or []),
            "pitch": list(pitches) if pitches else None,
            "tie": getattr(el, "tie", None),
        }
        if dur < -TIMELINE_TOL:
            issues.append({**base, "reason": "negative_duration"})
        elif dur <= TIMELINE_TOL:
            issues.append({**base, "reason": "zero_duration"})
        if start < -TIMELINE_TOL:
            issues.append({**base, "reason": "starts_before_zero"})
        if end > mql + 1e-6:
            issues.append({**base, "reason": "ends_after_measure"})
        if prev_end is not None and start < prev_end - 1e-6:
            issues.append({**base, "reason": "overlap", "previous_end": prev_end})
        elif prev_end is not None and start > prev_end + 1e-6:
            issues.append({**base, "reason": "gap", "previous_end": prev_end})
        total += max(0.0, dur)
        cursor = max(cursor, end)
        prev_end = end if prev_end is None else max(prev_end, end)
    if abs(total - mql) > VOICE_SUM_TOLERANCE:
        issues.append(
            {
                "reason": "sum_mismatch",
                "duration": total,
                "measure_length": mql,
                "end": cursor,
            }
        )
    return issues


@dataclass
class PlanBuildResult:
    """Explicit planner output. Callers must not scrape quantizer.last_result."""

    plan: NotationPlan
    decisions: list[dict]
    quantization: QuantizationResult


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
        quantization_mode: QuantizationMode | str | None = None,
    ) -> tuple[NotationPlan, list[dict]]:
        built = self.build_result(
            events,
            meta=meta,
            structure=structure,
            fallback_bpm=fallback_bpm,
            quantization_mode=quantization_mode,
        )
        return built.plan, built.decisions

    def build_result(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta | None = None,
        structure: MusicalStructure | None = None,
        fallback_bpm: float = 120.0,
        quantization_mode: QuantizationMode | str | None = None,
    ) -> PlanBuildResult:
        parsed = (
            parse_quantization_mode(quantization_mode)
            if quantization_mode is not None
            else QuantizationMode.PERFORMANCE
        )
        self.quantizer.mode = parsed
        meter = self._resolve_meter(events, meta, structure)
        if parsed == QuantizationMode.PERFORMANCE and meta and meta.tempo_map:
            extra = meta.extra or {}
            if extra.get("detected_downbeat_meter") == meter.time_signature:
                downbeats = [meta.tempo_map.seconds_to_beats(t)
                             for t in extra.get("detected_downbeats_seconds", [])]
                meter = replace(meter, evidence={**meter.evidence, "downbeat_beats": downbeats})
        if parsed == QuantizationMode.PERFORMANCE:
            quant_result = self.quantizer.quantize_production(events, meter)
        else:
            quant_result = self.quantizer.quantize_experimental(events, meter, parsed)
        quantized, decisions = quant_result.events, quant_result.decisions
        bpm = (meta.display_tempo_bpm if meta else None) or int(fallback_bpm)
        key_name = self._resolve_key(quantized, meta, structure)
        quant_summary = dict(quant_result.summary)

        pianoish = self._use_grand_staff(quantized, structure, meta)
        end_beat = 0.0
        if quantized:
            end_beat = max(e.start_beat + e.duration_beats for e in quantized)
        n_measures = max(1, int((end_beat + 1e-6) // meter.measure_quarter_length) + 1)
        # If music ends exactly on a boundary, don't add an extra empty bar.
        if quantized and abs(end_beat % meter.measure_quarter_length) < 1e-6:
            n_measures = max(1, int(round(end_beat / meter.measure_quarter_length)))

        measures: list[PlannedMeasure] = []
        production = quant_result.mode == QuantizationMode.PERFORMANCE.value
        if production:
            from notation_engine.exact_plan import build_exact_measures

            measures = build_exact_measures(quantized, quant_result.report, meter, key_name)
        for i in range(0 if production else n_measures):
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

        extra = {
            "meter_confidence": meter.confidence,
            "quantization": quant_summary,
            "invariant_issues": self._collect_plan_issues(measures),
        }
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
        return PlanBuildResult(
            plan=plan,
            decisions=list(decisions),
            quantization=quant_result,
        )

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

            primary_vid = min(voices_map)
            extra_vid = max(voices_map) + 1
            planned_voices = []
            occupied: set[int] = set()
            for orig_vid, items in sorted(voices_map.items()):
                lanes = self._serial_lanes(items)
                for i, lane in enumerate(lanes):
                    if i == 0 and orig_vid not in occupied:
                        vid = orig_vid
                    else:
                        vid = extra_vid
                        extra_vid += 1
                    occupied.add(vid)
                    planned_voices.append(
                        PlannedVoice(
                            voice_id=vid,
                            elements=self._fill_voice(
                                lane,
                                mql,
                                voice_id=vid,
                                hide_spacer_rests=vid != primary_vid,
                                measure_number=number,
                                staff_id=sid,
                            ),
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

    def _collect_plan_issues(self, measures: list[PlannedMeasure]) -> list[dict]:
        issues: list[dict] = []
        for measure in measures:
            for staff in measure.staves:
                for voice in staff.voices:
                    for issue in validate_voice_timeline(
                        voice.elements, measure.duration_beats
                    ):
                        packed = {
                            "measure": measure.number,
                            "staff": staff.staff_id,
                            "voice": voice.voice_id,
                            **issue,
                        }
                        issues.append(packed)
                        if issue.get("reason") in (
                            "overlap",
                            "ends_after_measure",
                            "negative_duration",
                            "zero_duration",
                            "starts_before_zero",
                        ):
                            log_notation_invariant("INVALID", **packed)
        return issues

    def _serial_lanes(self, items: list) -> list[list]:
        """Split a MIR voice into lanes that can be spelled without overlap.

        Same-onset notes with compatible durations stay together (chords).
        Different-duration same-onset notes and mid-note overlaps get their
        own lane so genuine polyphony is not serialized into overflow.
        """
        if not items:
            return [[]]
        ordered = sorted(items, key=lambda it: (it[1], it[0].pitch))
        lanes: list[list] = []
        for item in ordered:
            placed = False
            for lane in lanes:
                if self._fits_lane(lane, item):
                    lane.append(item)
                    placed = True
                    break
            if not placed:
                lanes.append([item])
        return lanes

    def _fits_lane(self, lane: list, item: tuple) -> bool:
        _ev, start, dur, _tie = item
        end = start + dur
        for other in lane:
            _oev, ostart, odur, _otie = other
            oend = ostart + odur
            if abs(start - ostart) <= TIMELINE_TOL and self._compatible_duration(
                dur, odur
            ):
                continue
            if start < oend - TIMELINE_TOL and ostart < end - TIMELINE_TOL:
                return False
        return True

    def _fill_voice(
        self,
        items: list,
        mql: float,
        voice_id: int = 0,
        hide_spacer_rests: bool = False,
        measure_number: int = 0,
        staff_id: int = 0,
    ) -> list:
        if not items:
            return [
                PlannedRest(
                    start_q=0.0,
                    duration_q=mql,
                    voice=voice_id,
                    hidden=False,
                )
            ]

        items = sorted(items, key=lambda it: (it[1], it[0].pitch))
        chords: list[list] = []
        for item in items:
            if chords and self._same_chord(chords[-1][0], item):
                chords[-1].append(item)
            else:
                chords.append([item])

        elements: list = []
        cursor = 0.0
        for group in chords:
            start = group[0][1]
            dur = max(it[2] for it in group)
            if not elements and 0.0 < start < REST_MIN_QL:
                start = 0.0
            if start < cursor - TIMELINE_TOL:
                prev = next(
                    (
                        el
                        for el in reversed(elements)
                        if isinstance(el, PlannedNote)
                    ),
                    None,
                )
                if prev is not None and abs(prev.start_q - start) < TIMELINE_TOL:
                    extra = sorted({it[0].pitch for it in group})
                    prev.pitches = sorted(set(prev.pitches) | set(extra))
                    ids = [it[0].note_id for it in group if it[0].note_id]
                    prev.event_ids = list(dict.fromkeys([*prev.event_ids, *ids]))
                    continue
                log_notation_invariant(
                    "INVALID",
                    measure=measure_number,
                    staff=staff_id,
                    voice=voice_id,
                    element="PlannedNote",
                    start=start,
                    duration=dur,
                    end=start + dur,
                    measure_length=mql,
                    event_ids=[it[0].note_id for it in group if it[0].note_id],
                    pitch=sorted({it[0].pitch for it in group}),
                    reason="same_voice_overlap",
                )
                start = cursor
            if start > cursor + REST_MIN_QL - TIMELINE_TOL:
                gap = start - cursor
                elements.extend(
                    self._rests(
                        cursor,
                        gap,
                        voice_id,
                        hidden=hide_spacer_rests,
                    )
                )
                cursor = start
            elif start > cursor + TIMELINE_TOL:
                # Tiny gap: keep the voice serial without a 32nd-or-smaller rest.
                prev = elements[-1] if elements else None
                if prev is not None:
                    prev.duration_q += start - cursor
                cursor = start
            dur = min(dur, max(0.0, mql - start))
            if dur <= TIMELINE_TOL:
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

        leftover = mql - cursor
        if leftover >= REST_MIN_QL - TIMELINE_TOL:
            elements.extend(
                self._rests(
                    cursor,
                    leftover,
                    voice_id,
                    hidden=hide_spacer_rests,
                )
            )
        elif leftover > TIMELINE_TOL and elements:
            elements[-1].duration_q += leftover

        if quantization_spells_writable(self.quantizer.mode):
            elements = self._spell_writable(
                elements,
                mql,
                voice_id,
                hide_spacer_rests=hide_spacer_rests,
            )

        self._assert_sum(elements, mql, voice_id, hide_spacer_rests=hide_spacer_rests)
        for issue in validate_voice_timeline(elements, mql):
            if issue.get("reason") in (
                "overlap",
                "ends_after_measure",
                "negative_duration",
                "zero_duration",
                "starts_before_zero",
            ):
                log_notation_invariant(
                    "INVALID",
                    measure=measure_number,
                    staff=staff_id,
                    voice=voice_id,
                    **issue,
                )
        return elements

    def _spell_writable(
        self,
        elements: list,
        mql: float,
        voice_id: int,
        hide_spacer_rests: bool = False,
    ) -> list:
        """Encode off-mode timing as tied named note types (no 32nd-grid snap)."""
        spelled: list = []
        cursor = 0.0
        for el in elements:
            remaining_bar = max(0.0, mql - cursor)
            if remaining_bar <= TIMELINE_TOL:
                break
            if isinstance(el, PlannedRest):
                hidden = bool(getattr(el, "hidden", False) or hide_spacer_rests)
                for d in duration_pieces(
                    el.duration_q, allow_empty=True, max_total=remaining_bar
                ):
                    if d < REST_MIN_QL - TIMELINE_TOL:
                        continue
                    spelled.append(
                        PlannedRest(
                            start_q=cursor,
                            duration_q=d,
                            voice=voice_id,
                            hidden=hidden,
                        )
                    )
                    cursor += d
                    remaining_bar = max(0.0, mql - cursor)
                continue

            orig_end = el.start_q + el.duration_q
            dur = min(max(0.0, orig_end - cursor), remaining_bar)
            pieces = duration_pieces(dur, allow_empty=False, max_total=remaining_bar)
            if not pieces:
                continue
            ties = tie_chain(len(pieces), el.tie)
            for i, d in enumerate(pieces):
                spelled.append(
                    PlannedNote(
                        pitches=list(el.pitches),
                        start_q=cursor,
                        duration_q=d,
                        voice=el.voice,
                        velocity=el.velocity,
                        tie=ties[i],
                        event_ids=list(el.event_ids),
                        articulations=list(el.articulations) if i == 0 else [],
                        dynamic=el.dynamic if i == 0 else None,
                    )
                )
                cursor += d

        leftover = mql - cursor
        if leftover >= REST_MIN_QL - TIMELINE_TOL:
            for d in duration_pieces(
                leftover, allow_empty=True, max_total=leftover
            ):
                if d < REST_MIN_QL - TIMELINE_TOL:
                    continue
                spelled.append(
                    PlannedRest(
                        start_q=cursor,
                        duration_q=d,
                        voice=voice_id,
                        hidden=hide_spacer_rests,
                    )
                )
                cursor += d
        elif leftover > TIMELINE_TOL and spelled:
            spelled[-1].duration_q += leftover
            cursor = mql
        if not spelled:
            for d in duration_pieces(mql, allow_empty=False, max_total=mql):
                spelled.append(
                    PlannedRest(
                        start_q=0.0 if not spelled else cursor,
                        duration_q=d,
                        voice=voice_id,
                        hidden=False,
                    )
                )
        return spelled

    def _same_chord(self, seed: tuple, item: tuple) -> bool:
        seed_ev, seed_start, seed_dur, _ = seed
        ev, start, dur, _ = item
        if ev.voice != seed_ev.voice:
            return False
        if staff_for_hand(ev.hand, ev.pitch) != staff_for_hand(seed_ev.hand, seed_ev.pitch):
            return False
        if abs(start - seed_start) > TIMELINE_TOL:
            return False
        return self._compatible_duration(seed_dur, dur)

    @staticmethod
    def _compatible_duration(a: float, b: float) -> bool:
        short, long = sorted((a, b))
        if long <= 1e-9:
            return True
        return short >= long * CHORD_DURATION_RATIO - 1e-9

    def _rests(
        self,
        start: float,
        duration: float,
        voice: int,
        hidden: bool = False,
    ) -> list[PlannedRest]:
        parts: list[PlannedRest] = []
        remaining = duration
        cursor = start
        if remaining <= TIMELINE_TOL:
            return parts
        if remaining < REST_MIN_QL - TIMELINE_TOL:
            return parts
        for d in REST_CANDIDATES:
            while remaining >= d - 1e-9:
                parts.append(
                    PlannedRest(
                        start_q=cursor,
                        duration_q=d,
                        voice=voice,
                        hidden=hidden,
                    )
                )
                cursor += d
                remaining -= d
        if remaining >= REST_MIN_QL - TIMELINE_TOL:
            parts.append(
                PlannedRest(
                    start_q=cursor,
                    duration_q=remaining,
                    voice=voice,
                    hidden=hidden,
                )
            )
        return parts

    def _assert_sum(
        self,
        elements: list,
        mql: float,
        voice_id: int = 0,
        hide_spacer_rests: bool = False,
    ) -> None:
        self._repair_sum(elements, mql, voice_id, hide_spacer_rests=hide_spacer_rests)
        total = sum(getattr(el, "duration_q", 0.0) for el in elements)
        if abs(total - mql) > VOICE_SUM_TOLERANCE:
            raise ValueError(
                f"voice {voice_id} elements sum to {total:.4f}, "
                f"expected measure duration {mql:.4f}"
            )

    def _repair_sum(
        self,
        elements: list,
        mql: float,
        voice_id: int,
        hide_spacer_rests: bool = False,
    ) -> None:
        if not elements:
            elements.append(
                PlannedRest(
                    start_q=0.0,
                    duration_q=mql,
                    voice=voice_id,
                    hidden=False,
                )
            )
            return
        total = sum(el.duration_q for el in elements)
        if abs(total - mql) <= TIMELINE_TOL:
            return
        if total > mql:
            extra = total - mql
            # Prefer trimming trailing rests (including hidden spacers) rather
            # than shortening sounding notes.
            for el in reversed(elements):
                if extra <= 1e-9:
                    break
                if isinstance(el, PlannedRest):
                    shrink = min(el.duration_q, extra)
                    el.duration_q -= shrink
                    extra -= shrink
            if extra > 1e-9:
                last = elements[-1]
                if last.duration_q > extra:
                    last.duration_q -= extra
                    extra = 0.0
            elements[:] = [el for el in elements if el.duration_q > TIMELINE_TOL]
            return
        gap = mql - total
        last = elements[-1]
        last_end = last.start_q + last.duration_q
        if gap < REST_MIN_QL - TIMELINE_TOL:
            last.duration_q += gap
            return
        if quantization_spells_writable(self.quantizer.mode):
            for d in duration_pieces(gap, allow_empty=True, max_total=gap):
                if d < REST_MIN_QL - TIMELINE_TOL:
                    continue
                elements.append(
                    PlannedRest(
                        start_q=last_end,
                        duration_q=d,
                        voice=voice_id,
                        hidden=hide_spacer_rests,
                    )
                )
                last_end += d
            leftover = mql - sum(el.duration_q for el in elements)
            if leftover > TIMELINE_TOL:
                elements[-1].duration_q += leftover
            return
        if isinstance(last, PlannedRest):
            last.duration_q += gap
        else:
            added = self._rests(last_end, gap, voice_id, hidden=hide_spacer_rests)
            if added:
                elements.extend(added)
            else:
                last.duration_q += gap
