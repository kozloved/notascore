"""Write MusicXML from MusicalEvent[] (source-agnostic).

Production export:

    MusicalEvents → MusicalStructure → NotationPlanner → NotationPlan
    → score_from_plan() → MusicXML

Legacy build_score() remains as a fallback if the planner raises.
"""

from __future__ import annotations

from pathlib import Path

from music21 import (
    articulations,
    chord as m21chord,
    clef,
    dynamics as m21dyn,
    instrument,
    key as m21key,
    layout,
    metadata as m21meta,
    meter,
    note as m21note,
    stream,
    tempo as m21tempo,
    tie as m21tie,
)

from mir.models import NotationPlan, PlannedRest
from mir.types import Hand, MusicalEvent, ScoreMeta, TempoMap
from notation_engine.meter import bar_length, estimate_key, estimate_time_signature
from notation_engine.plan import NotationPlanner
from notation_engine.quantize import quantize_events

CHORD_START_WINDOW = 0.08
CHORD_DURATION_RATIO = 0.5


class NotationWriter:
    """Convert CMR events to a piano grand-staff MusicXML score."""

    def __init__(self):
        self.planner = NotationPlanner()
        self.last_plan: NotationPlan | None = None
        self.last_quantization_decisions: list[dict] = []
        self.last_fallback_used: bool = False
        self.last_fallback_error: str | None = None

    def notation_debug_payload(self) -> dict:
        plan = self.last_plan
        return {
            "notation_path": (
                "legacy_build_score" if self.last_fallback_used else "notation_plan"
            ),
            "notation_fallback_error": self.last_fallback_error,
            "fallback_used": self.last_fallback_used,
            "time_signature": plan.time_signature if plan else None,
            "measure_count": len(plan.measures) if plan else 0,
            "quantization_decisions": list(self.last_quantization_decisions),
        }

    def write_musicxml(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        job_id: str,
        audio_path: Path,
        quantize_divisors: tuple[int, ...] = (4, 3),
        fallback_bpm: float = 120.0,
        structure=None,
    ) -> str:
        out_dir = Path(audio_path).parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)

        try:
            score = self._score_via_plan_or_legacy(
                events,
                meta,
                quantize_divisors=quantize_divisors,
                fallback_bpm=fallback_bpm,
                structure=structure,
            )
        except Exception as exc:
            print(f"[Notation] grand staff failed ({exc!s}), MIDI round-trip")
            if not self.last_fallback_used:
                self.last_fallback_used = True
                self.last_fallback_error = f"{type(exc).__name__}: {exc}"
            score = self._score_via_midi(
                events, meta, out_dir / f"{job_id}.mid", quantize_divisors, fallback_bpm
            )

        xml_path = out_dir / f"{job_id}.musicxml"
        score.write("musicxml", fp=str(xml_path))
        score.write("midi", fp=str(out_dir / f"{job_id}.score.mid"))
        return xml_path.read_text(encoding="utf-8")

    def write_from_events_direct(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        quantize_divisors: tuple[int, ...] = (4, 3),
        structure=None,
    ) -> stream.Score:
        """Build a music21 score without writing files (tests / production path)."""
        return self._score_via_plan_or_legacy(
            events,
            meta,
            quantize_divisors=quantize_divisors,
            fallback_bpm=float(meta.display_tempo_bpm or 120),
            structure=structure,
        )

    def _score_via_plan_or_legacy(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        *,
        quantize_divisors: tuple[int, ...],
        fallback_bpm: float,
        structure=None,
    ) -> stream.Score:
        self.last_plan = None
        self.last_quantization_decisions = []
        self.last_fallback_used = False
        self.last_fallback_error = None
        try:
            plan, decisions = self.planner.build(
                events,
                meta=meta,
                structure=structure,
                fallback_bpm=fallback_bpm,
            )
            score = self.score_from_plan(plan, meta=meta)
            self.last_plan = plan
            self.last_quantization_decisions = decisions
            print(
                f"[Notation] NotationPlan "
                f"({plan.time_signature}, {len(plan.measures)} measures, "
                f"{len(decisions)} quantized events)"
            )
            return score
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            print(f"[Notation] NotationPlanner failed ({reason}); falling back to legacy build_score")
            self.last_fallback_used = True
            self.last_fallback_error = reason
            return self.build_score(
                events,
                meta,
                quantize_divisors=quantize_divisors,
                fallback_bpm=fallback_bpm,
            )

    def write_from_plan(self, plan: NotationPlan) -> stream.Score:
        return self.score_from_plan(plan)

    def score_from_plan(
        self, plan: NotationPlan, meta: ScoreMeta | None = None
    ) -> stream.Score:
        score = stream.Score()
        md = m21meta.Metadata()
        md.movementName = None
        md.composer = None
        score.insert(0, md)

        n_staves = 0
        for measure in plan.measures:
            for staff in measure.staves:
                n_staves = max(n_staves, staff.staff_id + 1)
        n_staves = max(1, n_staves)

        parts: list[stream.PartStaff] = []
        for sid in range(n_staves):
            part = stream.PartStaff(id=f"P1-Staff{sid + 1}")
            part.partName = "Piano" if n_staves >= 2 else "Music"
            part.partAbbreviation = "Pno." if n_staves >= 2 else "Mus."
            part.insert(0, instrument.Piano())
            parts.append(part)
            score.insert(0, part)

        if n_staves >= 2:
            group = layout.StaffGroup(
                parts[:2],
                name="Piano",
                abbreviation="Pno.",
                symbol="brace",
                barTogether=True,
            )
            score.insert(0, group)

        for mi, measure_plan in enumerate(plan.measures):
            by_staff = {s.staff_id: s for s in measure_plan.staves}
            for sid, part in enumerate(parts):
                staff = by_staff.get(sid)
                m = stream.Measure(number=measure_plan.number)
                m.duration.quarterLength = measure_plan.duration_beats
                if mi == 0:
                    clef_name = staff.clef if staff else ("treble" if sid == 0 else "bass")
                    m.insert(0, self._clef(clef_name))
                    m.insert(0, meter.TimeSignature(plan.time_signature))
                    try:
                        m.insert(0, m21key.Key(plan.key_signature))
                    except Exception:
                        m.insert(0, m21key.Key("C"))
                if staff is None:
                    rest_voice = stream.Voice(id="1")
                    rest_voice.append(
                        m21note.Rest(quarterLength=measure_plan.duration_beats)
                    )
                    m.insert(0, rest_voice)
                else:
                    for vplan in staff.voices:
                        voice = stream.Voice(id=str(vplan.voice_id + 1))
                        for el in vplan.elements:
                            voice.append(self._element_to_m21(el))
                        m.insert(0, voice)
                part.append(m)

        bpm = int(plan.tempo_bpm)
        if meta and meta.display_tempo_bpm:
            bpm = int(meta.display_tempo_bpm)
        # Metronome marks must live in a measure. A score-level mark survives
        # in memory but music21 omits it from MusicXML, so OSMD never draws BPM.
        self._insert_metronome_at_beat(score, 0.0, bpm)
        if meta is not None:
            self._apply_tempo_map(score, meta)
        return score

    def _element_to_m21(self, el):
        if isinstance(el, PlannedRest):
            return m21note.Rest(quarterLength=float(el.duration_q))
        if len(el.pitches) == 1:
            n = m21note.Note(midi=int(el.pitches[0]))
        else:
            n = m21chord.Chord([int(p) for p in el.pitches])
        n.quarterLength = float(el.duration_q)
        try:
            n.volume.velocity = int(el.velocity)
        except Exception:
            pass
        if el.tie:
            n.tie = m21tie.Tie(el.tie)
        if "staccato" in el.articulations:
            n.articulations.append(articulations.Staccato())
        if "legato" in el.articulations:
            n.articulations.append(articulations.Tenuto())
        if el.dynamic in ("p", "pp", "mp", "mf", "f", "ff", "fff"):
            n.expressions.append(m21dyn.Dynamic(el.dynamic))
        return n

    def _clef(self, name: str):
        if name == "bass":
            return clef.BassClef()
        return clef.TrebleClef()

    def build_score(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        quantize_divisors: tuple[int, ...] = (4, 3),
        fallback_bpm: float = 120.0,
    ) -> stream.Score:
        quantized = quantize_events(events, quantize_divisors)
        ts_str = meta.time_sig_hint or estimate_time_signature(quantized)
        key_name = meta.key_hint or estimate_key(quantized)
        bpm = meta.display_tempo_bpm or int(fallback_bpm)
        bar_ql = bar_length(ts_str)
        end_beat = _span_beats(quantized, bar_ql)

        rh_events = [e for e in quantized if _staff_for(e) == "rh"]
        lh_events = [e for e in quantized if _staff_for(e) == "lh"]

        rh = self._build_staff(
            rh_events,
            staff_id="P1-Staff1",
            staff_clef=clef.TrebleClef(),
            ts_str=ts_str,
            key_name=key_name,
            end_beat=end_beat,
        )
        lh = self._build_staff(
            lh_events,
            staff_id="P1-Staff2",
            staff_clef=clef.BassClef(),
            ts_str=ts_str,
            key_name=key_name,
            end_beat=end_beat,
        )

        score = stream.Score()
        md = m21meta.Metadata()
        md.movementName = None
        md.composer = None
        score.insert(0, md)
        score.insert(0, rh)
        score.insert(0, lh)
        group = layout.StaffGroup(
            [rh, lh],
            name="Piano",
            abbreviation="Pno.",
            symbol="brace",
            barTogether=True,
        )
        score.insert(0, group)
        score.makeNotation(inPlace=True, refStreamOrTimeRange=[0.0, end_beat])
        # Metronome marks must live in a measure. A score-level mark survives
        # in memory but music21 omits it from MusicXML, so OSMD never draws BPM.
        self._insert_metronome_at_beat(score, 0.0, int(bpm))
        self._apply_tempo_map(score, meta)
        return score

    def _build_staff(
        self,
        events: list[MusicalEvent],
        *,
        staff_id: str,
        staff_clef,
        ts_str: str,
        key_name: str | None,
        end_beat: float,
    ) -> stream.PartStaff:
        part = stream.PartStaff(id=staff_id)
        part.partName = "Piano"
        part.partAbbreviation = "Pno."
        part.insert(0, instrument.Piano())
        part.insert(0, staff_clef)
        part.insert(0, meter.TimeSignature(ts_str))
        if key_name:
            try:
                part.insert(0, m21key.Key(key_name))
            except Exception:
                pass

        for start, group in _chord_clusters(events):
            part.insert(start, self._m21_element(group))

        if not events:
            part.insert(0, m21note.Rest(quarterLength=max(end_beat, 1.0)))
        return part

    def _m21_element(self, group: list[MusicalEvent]):
        duration = max(e.duration_beats for e in group)
        if len(group) == 1:
            el = m21note.Note(group[0].pitch)
            el.volume.velocity = max(1, min(127, int(group[0].velocity)))
        else:
            el = m21chord.Chord([e.pitch for e in group])
            el.volume.velocity = max(
                1, min(127, int(sum(e.velocity for e in group) / len(group)))
            )
        el.quarterLength = duration
        self._style_element(el, group)
        return el

    def _style_element(self, el, group: list[MusicalEvent]) -> None:
        arts = {e.articulation for e in group if e.articulation}
        if "staccato" in arts:
            el.articulations.append(articulations.Staccato())
        elif "legato" in arts:
            el.articulations.append(articulations.Tenuto())
        marks = [e.dynamic for e in group if e.dynamic]
        if marks:
            mark = marks[0]
            if mark in ("p", "pp", "mp", "mf", "f", "ff"):
                el.expressions.append(m21dyn.Dynamic(mark))

    def _score_via_midi(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        midi_path: Path,
        quantize_divisors: tuple[int, ...],
        fallback_bpm: float,
    ) -> stream.Score:
        from music21 import converter
        import pretty_midi

        bpm = meta.display_tempo_bpm or int(fallback_bpm)
        midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        rh = pretty_midi.Instrument(program=0, name="RH")
        lh = pretty_midi.Instrument(program=0, name="LH")
        spb = 60.0 / bpm
        for ev in events:
            inst = lh if _staff_for(ev) == "lh" else rh
            inst.notes.append(
                pretty_midi.Note(
                    velocity=ev.velocity,
                    pitch=ev.pitch,
                    start=ev.start_beat * spb,
                    end=(ev.start_beat + ev.duration_beats) * spb,
                )
            )
        if rh.notes:
            midi.instruments.append(rh)
        if lh.notes:
            midi.instruments.append(lh)
        if not midi.instruments:
            midi.instruments.append(pretty_midi.Instrument(program=0))
        midi.write(str(midi_path))
        score = converter.parse(str(midi_path))
        score.quantize(
            quarterLengthDivisors=quantize_divisors,
            processOffsets=True,
            processDurations=True,
            inPlace=True,
            recurse=True,
        )
        self._insert_metronome_at_beat(score, 0.0, int(bpm))
        self._apply_tempo_map(score, meta)
        return score

    def _apply_tempo_map(self, score, meta: ScoreMeta) -> None:
        tempo_map: TempoMap | None = meta.tempo_map
        if tempo_map is None or len(tempo_map.sorted_points()) < 2:
            return
        from transcription import snap_to_standard_tempo

        last_bpm = float(meta.display_tempo_bpm or 120)
        for pt in tempo_map.sorted_points():
            if pt.time_sec <= 1e-6:
                continue
            snapped = float(snap_to_standard_tempo(pt.bpm))
            if abs(snapped - last_bpm) / max(last_bpm, 1.0) < 0.08:
                continue
            offset = tempo_map.seconds_to_beats(pt.time_sec)
            if offset <= 0:
                continue
            self._insert_metronome_at_beat(score, offset, int(snapped))
            last_bpm = snapped

    @staticmethod
    def _insert_metronome_at_beat(score, beat: float, bpm: int) -> None:
        """Put a metronome mark inside the measure that OSMD/MusicXML will export."""
        mark = m21tempo.MetronomeMark(number=int(bpm))
        try:
            mark.placement = "above"
        except Exception:
            pass
        part = score.parts[0] if getattr(score, "parts", None) else score
        measures = list(part.getElementsByClass("Measure"))
        if not measures:
            part.insert(max(0.0, float(beat)), mark)
            return
        for meas in measures:
            start = float(meas.offset)
            try:
                dur = float(meas.barDuration.quarterLength)
            except Exception:
                dur = float(getattr(meas.duration, "quarterLength", 4.0) or 4.0)
            if start - 1e-6 <= float(beat) < start + dur - 1e-9:
                local = max(0.0, float(beat) - start)
                existing = [
                    item
                    for item in meas.getElementsByClass(m21tempo.MetronomeMark)
                    if abs(float(item.offset) - local) < 1e-6
                ]
                if existing:
                    existing[0].number = int(bpm)
                    return
                meas.insert(local, mark)
                return
        first = measures[0]
        existing = list(first.getElementsByClass(m21tempo.MetronomeMark))
        if existing:
            existing[0].number = int(bpm)
            return
        first.insert(0, mark)


def _staff_for(ev: MusicalEvent) -> str:
    # UNKNOWN/AMBIGUOUS keep that label on the event. Staff placement here is
    # only a temporary fallback so MusicXML still has a staff.
    if ev.hand == Hand.LEFT:
        return "lh"
    if ev.hand == Hand.RIGHT:
        return "rh"
    return "lh" if ev.pitch < 60 else "rh"


def _span_beats(events: list[MusicalEvent], bar_ql: float) -> float:
    import math

    if not events:
        return max(bar_ql, 4.0)
    raw = max(e.start_beat + e.duration_beats for e in events)
    return max(bar_ql, math.ceil((raw - 1e-9) / bar_ql) * bar_ql)


def _is_chord_mate(a: MusicalEvent, b: MusicalEvent) -> bool:
    if abs(a.start_beat - b.start_beat) > CHORD_START_WINDOW:
        return False
    short, long = sorted((a.duration_beats, b.duration_beats))
    return short >= long * CHORD_DURATION_RATIO


def _chord_clusters(events: list[MusicalEvent]) -> list[tuple[float, list[MusicalEvent]]]:
    if not events:
        return []
    remaining = sorted(events, key=lambda e: (e.start_beat, e.pitch))
    clusters: list[tuple[float, list[MusicalEvent]]] = []
    used = [False] * len(remaining)
    for i, seed in enumerate(remaining):
        if used[i]:
            continue
        group = [seed]
        used[i] = True
        for j in range(i + 1, len(remaining)):
            if used[j]:
                continue
            if _is_chord_mate(seed, remaining[j]):
                group.append(remaining[j])
                used[j] = True
        clusters.append((seed.start_beat, group))
    return clusters
