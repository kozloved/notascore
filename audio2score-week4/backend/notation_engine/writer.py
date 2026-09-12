"""Write MusicXML from MusicalEvent[] (source-agnostic).

Production export:

    MusicalEvents → MusicalStructure → NotationPlanner → NotationPlan
    → score_from_plan() → MusicXML

Legacy build_score() remains as a fallback if the planner raises.
"""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory

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
from music21.base import Music21Object

from mir.job import NotationResult
from mir.models import NotationPlan, PlannedRest
from mir.quantizer import SMALLEST_WRITABLE, snap_writable_length
from mir.types import Hand, MusicalEvent, ScoreMeta, TempoMap
from notation_engine.meter import bar_length, estimate_key, estimate_time_signature
from notation_engine.plan import NotationPlanner, log_notation_invariant, validate_voice_timeline
from notation_engine.quantize import quantize_events
from notation_engine.integrity import NotationIntegrityError, validate_event_identity, validate_exports
from mir.pipeline_config import (
    QuantizationMode,
    parse_quantization_mode,
    quantization_skips_legacy_grid,
    quantization_snaps_display_tempo,
)

CHORD_START_WINDOW = 0.08
CHORD_DURATION_RATIO = 0.5


class NotationWriter:
    """Convert CMR events to a piano grand-staff MusicXML score."""

    def __init__(self):
        self.planner = NotationPlanner()
        self.last_plan: NotationPlan | None = None
        self.last_quantization_decisions: list[dict] = []
        self.last_quantization_summary: dict = {}
        self.last_quantized_events: list = []
        self.last_fallback_used: bool = False
        self.last_fallback_error: str | None = None
        self.last_quantization_mode: QuantizationMode = parse_quantization_mode(None)
        self.last_job_id: str | None = None
        self.last_source_event_count: int = 0
        self.last_plan_failure: bool = False
        self.last_conversion_failure: bool = False
        self.last_export_failure: bool = False
        self.last_fit_trim_count: int = 0
        self.last_invariant_issues: list[dict] = []
        self.last_result: NotationResult | None = None
        self.last_export_integrity: dict = {}

    def _remember_notation(self, result: NotationResult) -> None:
        self.last_result = result
        self.last_plan = result.plan
        self.last_quantization_decisions = list(result.decisions)
        self.last_quantization_summary = dict(result.summary)
        self.last_quantized_events = list(result.quantized_events)
        self.last_fallback_used = result.fallback_used
        self.last_fallback_error = result.fallback_error
        self.last_quantization_mode = parse_quantization_mode(result.quantization_mode)
        self.last_job_id = result.job_id
        self.last_source_event_count = result.source_event_count
        self.last_plan_failure = result.plan_failure
        self.last_conversion_failure = result.conversion_failure
        self.last_export_failure = result.export_failure
        self.last_fit_trim_count = result.fit_trim_count
        self.last_invariant_issues = list(result.invariant_issues)

    def notation_debug_payload(self) -> dict:
        if self.last_result is not None:
            payload = self.last_result.to_debug_payload()
            payload["fit_trim_count"] = self.last_fit_trim_count
            payload["invariant_issues"] = list(self.last_invariant_issues)
            payload["musicxml_export_failure"] = self.last_export_failure
            payload["export_integrity"] = dict(self.last_export_integrity)
            payload["score_is_hypothesis"] = True
            payload["readability_requires_human"] = True
            payload["source_identity_gate"] = (
                self.last_quantization_mode == QuantizationMode.PERFORMANCE
            )
            return payload
        plan = self.last_plan
        plan_ok = plan is not None and not self.last_plan_failure
        return {
            "notation_path": (
                "legacy_build_score" if self.last_fallback_used else "notation_plan"
            ),
            "notation_mode": self.last_quantization_mode.value,
            "notation_plan_success": plan_ok and not self.last_conversion_failure,
            "notation_plan_failure": self.last_plan_failure,
            "legacy_fallback_used": self.last_fallback_used,
            "music21_conversion_failure": self.last_conversion_failure,
            "musicxml_export_failure": self.last_export_failure,
            "notation_fallback_error": self.last_fallback_error,
            "fallback_used": self.last_fallback_used,
            "job_id": self.last_job_id,
            "source_event_count": self.last_source_event_count,
            "quantized_event_count": len(self.last_quantized_events or []),
            "time_signature": plan.time_signature if plan else None,
            "measure_count": len(plan.measures) if plan else 0,
            "fit_trim_count": self.last_fit_trim_count,
            "invariant_issues": list(self.last_invariant_issues),
            "quantization_decisions": list(self.last_quantization_decisions),
            "quantization_summary": dict(self.last_quantization_summary),
            "export_integrity": dict(self.last_export_integrity),
            "score_is_hypothesis": True,
            "readability_requires_human": True,
            "source_identity_gate": self.last_quantization_mode == QuantizationMode.PERFORMANCE,
        }

    def write_musicxml(
        self, events, meta, job_id, audio_path, quantize_divisors=(4, 3),
        fallback_bpm=120.0, structure=None, quantization_mode=None,
    ) -> str:
        out_dir = Path(audio_path).parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)
        self.last_export_integrity = {}
        # Failed validation must not publish a partial or corrupted score.
        with TemporaryDirectory(prefix=".notation-", dir=out_dir) as staging:
            staged_source = Path(staging) / Path(audio_path).name
            try:
                xml = self._write_musicxml_files(
                    events, meta, job_id, staged_source, quantize_divisors,
                    fallback_bpm, structure, quantization_mode)
            except NotationIntegrityError as exc:
                self.last_export_failure = True
                self.last_export_integrity = {"status": "failed", "error": str(exc)}
                raise
            for artifact in (Path(staging) / f"bp_{job_id}").iterdir():
                artifact.replace(out_dir / artifact.name)
        return xml

    def _write_musicxml_files(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        job_id: str,
        audio_path: Path,
        quantize_divisors: tuple[int, ...] = (4, 3),
        fallback_bpm: float = 120.0,
        structure=None,
        quantization_mode: QuantizationMode | str | None = None,
    ) -> str:
        out_dir = Path(audio_path).parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)
        self.last_job_id = job_id
        self.last_source_event_count = len(events)
        self.last_export_failure = False

        try:
            score = self._score_via_plan_or_legacy(
                events,
                meta,
                quantize_divisors=quantize_divisors,
                fallback_bpm=fallback_bpm,
                structure=structure,
                quantization_mode=quantization_mode,
            )
        except Exception as exc:
            if self.last_quantization_mode == QuantizationMode.PERFORMANCE:
                raise
            print(f"[Notation] grand staff failed ({exc!s}), MIDI round-trip")
            if not self.last_fallback_used:
                self.last_fallback_used = True
                self.last_fallback_error = f"{type(exc).__name__}: {exc}"
            score = self._score_via_midi(
                events,
                meta,
                out_dir / f"{job_id}.mid",
                quantize_divisors,
                fallback_bpm,
                quantization_mode=quantization_mode,
            )

        xml_path = out_dir / f"{job_id}.musicxml"
        try:
            self._export_musicxml(score, xml_path)
        except Exception as exc:
            if self.last_quantization_mode == QuantizationMode.PERFORMANCE:
                self.last_export_failure = True
                raise
            print(f"[Notation] MusicXML export failed ({exc!s}), MIDI round-trip")
            self.last_export_failure = True
            if not self.last_fallback_used:
                self.last_fallback_used = True
                self.last_fallback_error = f"{type(exc).__name__}: {exc}"
            score = self._score_via_midi(
                events,
                meta,
                out_dir / f"{job_id}.mid",
                quantize_divisors,
                fallback_bpm,
                quantization_mode=quantization_mode,
            )
            self._export_musicxml(score, xml_path)
        try:
            playback = self._score_for_playback(score, meta)
            playback.write("midi", fp=str(out_dir / f"{job_id}.score.mid"))
        except Exception as exc:
            if self.last_quantization_mode == QuantizationMode.PERFORMANCE:
                raise NotationIntegrityError(f"Score MIDI export failed: {exc}") from exc
            print(f"[Notation] score MIDI write failed ({exc!s})")
        if self.last_quantization_mode == QuantizationMode.PERFORMANCE:
            validate_event_identity(events, self.last_quantized_events)
            self.last_export_integrity = validate_exports(
                xml_path, out_dir / f"{job_id}.score.mid", self.last_quantized_events)
        else:
            self.last_export_integrity = {
                "status": "skipped",
                "reason": "source identity gate is production performance only",
                "quantization_mode": self.last_quantization_mode.value,
                "lossless": False,
            }
        return xml_path.read_text(encoding="utf-8")

    def _score_for_playback(self, score, meta):
        from notation_engine.playback import playback_score

        tempi = (meta.extra or {}).get("playback_tempo")
        if self.last_quantization_mode != QuantizationMode.PERFORMANCE:
            return score
        # The page keeps sparse markings; MIDI needs the full score-time curve.
        offset = float(self.last_quantization_summary.get("score_beat_offset", 0.0))
        if tempi:
            points = {0.0: float(tempi[0]["bpm"])}
            points.update({float(p["beat"]) + offset: float(p["bpm"]) for p in tempi
                           if 0 <= float(p["beat"]) + offset < float(score.highestTime)})
        else:
            points = {float(m.getOffsetInHierarchy(score.parts[0])): float(m.number)
                      for m in score.parts[0].recurse().getElementsByClass(m21tempo.MetronomeMark)
                      if m.number is not None}
        return playback_score(self.last_quantized_events, self.last_plan.time_signature,
                              sorted(points.items()))

    def write_from_events_direct(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        quantize_divisors: tuple[int, ...] = (4, 3),
        structure=None,
        quantization_mode: QuantizationMode | str | None = None,
    ) -> stream.Score:
        """Build a music21 score without writing files (tests / production path)."""
        return self._score_via_plan_or_legacy(
            events,
            meta,
            quantize_divisors=quantize_divisors,
            fallback_bpm=float(meta.display_tempo_bpm or 120),
            structure=structure,
            quantization_mode=quantization_mode,
        )

    def _score_via_plan_or_legacy(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        *,
        quantize_divisors: tuple[int, ...],
        fallback_bpm: float,
        structure=None,
        quantization_mode: QuantizationMode | str | None = None,
    ) -> stream.Score:
        mode = (
            parse_quantization_mode(quantization_mode)
            if quantization_mode is not None
            else parse_quantization_mode(None)
        )
        result = NotationResult(
            quantization_mode=mode.value,
            source_event_count=len(events),
            job_id=self.last_job_id,
        )
        self.last_quantization_mode = mode
        self.last_plan = None
        self.last_quantization_decisions = []
        self.last_quantization_summary = {}
        self.last_quantized_events = []
        self.last_fallback_used = False
        self.last_fallback_error = None
        self.last_plan_failure = False
        self.last_conversion_failure = False
        self.last_fit_trim_count = 0
        self.last_invariant_issues = []
        self.last_source_event_count = len(events)
        self.last_result = result
        plan = None
        decisions: list[dict] = []
        try:
            plan, decisions = self.planner.build(
                events,
                meta=meta,
                structure=structure,
                fallback_bpm=fallback_bpm,
                quantization_mode=mode,
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            result.plan_failure = True
            result.fallback_error = reason
            if mode == QuantizationMode.PERFORMANCE:
                self._remember_notation(result)
                raise
            print(f"[Notation] NotationPlanner failed ({reason}); falling back to legacy build_score")
            result.fallback_used = True
            self._remember_notation(result)
            return self.build_score(
                events,
                meta,
                quantize_divisors=quantize_divisors,
                fallback_bpm=fallback_bpm,
                quantization_mode=mode,
            )
        try:
            score = self.score_from_plan(plan, meta=meta)
            quant_result = getattr(self.planner.quantizer, "last_result", None)
            result.plan = plan
            result.decisions = decisions
            result.summary = dict((plan.extra or {}).get("quantization") or {})
            result.quantized_events = list(
                quant_result.events if quant_result is not None else self.planner.quantizer.last_events
            )
            result.invariant_issues = list(
                (plan.extra or {}).get("invariant_issues") or []
            )
            result.fit_trim_count = self.last_fit_trim_count
            self._remember_notation(result)
            print(
                f"[Notation] NotationPlan "
                f"job={self.last_job_id or '-'} "
                f"mode={mode.value} "
                f"source_events={len(events)} "
                f"quantized_events={len(result.quantized_events)} "
                f"({plan.time_signature}, {len(plan.measures)} measures, "
                f"{len(decisions)} quantized events)"
            )
            return score
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            result.plan = plan
            result.decisions = decisions
            result.conversion_failure = True
            result.fallback_error = reason
            if mode == QuantizationMode.PERFORMANCE:
                self._remember_notation(result)
                raise
            print(
                f"[Notation] music21 conversion failed ({reason}); "
                "falling back to legacy build_score"
            )
            result.fallback_used = True
            self._remember_notation(result)
            return self.build_score(
                events,
                meta,
                quantize_divisors=quantize_divisors,
                fallback_bpm=fallback_bpm,
                quantization_mode=mode,
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
        self._safe_insert(score, 0, md)

        n_staves = 0
        for measure in plan.measures:
            for staff in measure.staves:
                n_staves = max(n_staves, staff.staff_id + 1)
        n_staves = max(1, n_staves)

        parts: list[stream.PartStaff] = []
        profile = (plan.extra.get("quantization") or {}).get("score_profile", {})
        program = profile.get("program")
        for sid in range(n_staves):
            part = (stream.PartStaff if n_staves >= 2 else stream.Part)(id=f"P1-Staff{sid + 1}")
            part.partName = "Piano" if n_staves >= 2 else "Music"
            part.partAbbreviation = "Pno." if n_staves >= 2 else "Mus."
            inst = instrument.instrumentFromMidiProgram(program) if program is not None else (
                instrument.Piano() if n_staves >= 2 else instrument.Instrument())
            if program is not None:
                part.partName = inst.instrumentName
                part.partAbbreviation = inst.instrumentAbbreviation
            self._safe_insert(part, 0, inst)
            parts.append(part)
            self._safe_insert(score, 0, part)

        if n_staves >= 2:
            group = layout.StaffGroup(
                parts[:2],
                name="Piano",
                abbreviation="Pno.",
                symbol="brace",
                barTogether=True,
            )
            self._safe_insert(score, 0, group)

        for mi, measure_plan in enumerate(plan.measures):
            by_staff = {s.staff_id: s for s in measure_plan.staves}
            measure_ql = max(float(measure_plan.duration_beats or 0.0), SMALLEST_WRITABLE)
            for sid, part in enumerate(parts):
                staff = by_staff.get(sid)
                m = stream.Measure(number=measure_plan.number)
                m.duration.quarterLength = measure_ql
                if mi == 0:
                    clef_name = staff.clef if staff else ("treble" if sid == 0 else "bass")
                    self._safe_insert(m, 0, self._clef(clef_name))
                    self._safe_insert(m, 0, self._time_signature(plan.time_signature))
                    self._safe_insert(m, 0, self._key_signature(plan.key_signature))
                if staff is None:
                    rest_voice = stream.Voice(id="1")
                    rest = self._rest_for_length(measure_ql)
                    if rest is not None:
                        self._safe_append(rest_voice, rest)
                    self._safe_insert(m, 0, rest_voice)
                else:
                    for vplan in staff.voices:
                        voice = stream.Voice(id=str(vplan.voice_id + 1))
                        for issue in validate_voice_timeline(vplan.elements, measure_ql):
                            if issue.get("reason") in (
                                "overlap",
                                "ends_after_measure",
                                "negative_duration",
                                "zero_duration",
                                "starts_before_zero",
                            ):
                                log_notation_invariant(
                                    "INVALID",
                                    job_id=self.last_job_id,
                                    notation_mode=self.last_quantization_mode.value,
                                    measure=measure_plan.number,
                                    staff=sid,
                                    voice=vplan.voice_id,
                                    **issue,
                                )
                        for el in vplan.elements:
                            m21el = self._element_to_m21(el)
                            converted = m21el is not None
                            if not converted:
                                log_notation_invariant(
                                    "SKIP",
                                    job_id=self.last_job_id,
                                    measure=measure_plan.number,
                                    staff=sid,
                                    voice=vplan.voice_id,
                                    element=type(el).__name__,
                                    start=getattr(el, "start_q", None),
                                    duration=getattr(el, "duration_q", None),
                                    event_ids=list(getattr(el, "event_ids", None) or []),
                                    pitch=list(getattr(el, "pitches", None) or []),
                                    tie=getattr(el, "tie", None),
                                    converted=False,
                                )
                            self._safe_append(voice, m21el)
                        if not list(voice.notesAndRests):
                            rest = self._rest_for_length(measure_ql)
                            self._safe_append(voice, rest)
                        before_trim = self.last_fit_trim_count
                        self._fit_stream_to_quarter_length(
                            voice,
                            measure_ql,
                            measure_number=measure_plan.number,
                            staff_id=sid,
                            voice_id=vplan.voice_id,
                        )
                        if self.last_fit_trim_count > before_trim:
                            log_notation_invariant(
                                "TRIM",
                                job_id=self.last_job_id,
                                measure=measure_plan.number,
                                staff=sid,
                                voice=vplan.voice_id,
                                measure_length=measure_ql,
                            )
                        self._safe_insert(m, 0, voice)
                self._safe_append(part, m)

        bpm = int(plan.tempo_bpm)
        if meta and meta.display_tempo_bpm:
            bpm = int(meta.display_tempo_bpm)
        # Metronome marks must live in a measure. A score-level mark survives
        # in memory but music21 omits it from MusicXML, so OSMD never draws BPM.
        self._insert_metronome_at_beat(score, 0.0, bpm)
        if meta is not None:
            self._apply_tempo_map(score, meta, score_beat_offset=float(
                (plan.extra.get("quantization") or {}).get("score_beat_offset", 0)))
        return score

    def _element_to_m21(self, el):
        ql = float(getattr(el, "duration_q", 0.0) or 0.0)
        if ql <= 1e-8:
            return None
        if isinstance(el, PlannedRest):
            rest = self._rest_for_length(ql)
            if rest is not None:
                self._apply_planned_rhythm(rest, el)
            if rest is not None and getattr(el, "hidden", False):
                rest.hideObjectOnPrint = True
                try:
                    rest.style.hideObjectOnPrint = True
                except Exception:
                    pass
            return rest
        pitches: list[int] = []
        for raw in getattr(el, "pitches", None) or []:
            try:
                midi = int(raw)
            except (TypeError, ValueError):
                continue
            if 0 <= midi <= 127:
                pitches.append(midi)
        if not pitches:
            return self._rest_for_length(ql)
        if len(pitches) == 1:
            n = m21note.Note(midi=pitches[0])
        else:
            # Chord([MIDI integers]) adds explicit naturals to white keys,
            # causing repeated courtesy signs after export. Note(midi=...)
            # leaves accidental spelling to the actual key/measure context.
            n = m21chord.Chord([m21note.Note(midi=p) for p in pitches])
        n.quarterLength = ql
        self._apply_planned_rhythm(n, el)
        try:
            n.volume.velocity = int(el.velocity)
        except Exception:
            pass
        velocities = getattr(el, "velocities", [])
        if velocities and len(velocities) == len(pitches):
            if isinstance(n, m21chord.Chord):
                for component, velocity in zip(n.notes, velocities):
                    component.volume.velocity = int(velocity)
            else:
                n.volume.velocity = int(velocities[0])
        if getattr(el, "tie", None) in ("start", "stop", "continue"):
            n.tie = m21tie.Tie(el.tie)
        arts = getattr(el, "articulations", None) or []
        if "staccato" in arts:
            n.articulations.append(articulations.Staccato())
        if "legato" in arts:
            n.articulations.append(articulations.Tenuto())
        dynamic = getattr(el, "dynamic", None)
        if dynamic in ("p", "pp", "mp", "mf", "f", "ff", "fff"):
            n.expressions.append(m21dyn.Dynamic(dynamic))
        return n

    @staticmethod
    def _apply_planned_rhythm(obj, element):
        for beam_type, direction in getattr(element, "beams", []):
            obj.beams.append(beam_type, direction)
        planned = getattr(element, "tuplet", None)
        if planned is not None:
            tuplets = obj.duration.tuplets
            if len(tuplets) != 1 or (tuplets[0].numberNotesActual, tuplets[0].numberNotesNormal) != (planned.actual, planned.normal):
                raise ValueError("Export duration disagrees with planned tuplet ratio")
            tuplets[0].type = planned.boundary

    def _clef(self, name: str):
        if name == "bass":
            return clef.BassClef()
        return clef.TrebleClef()

    @staticmethod
    def _time_signature(value) -> meter.TimeSignature:
        try:
            ts = meter.TimeSignature(value or "4/4")
            if float(ts.barDuration.quarterLength) <= 0:
                raise ValueError("empty bar duration")
            return ts
        except Exception:
            return meter.TimeSignature("4/4")

    @staticmethod
    def _key_signature(value):
        try:
            if not value:
                return m21key.Key("C")
            return m21key.Key(str(value))
        except Exception:
            return m21key.Key("C")

    @staticmethod
    def _rest_for_length(ql: float):
        ql = float(ql or 0.0)
        if ql <= 1e-8:
            return None
        # music21 coerces Rest(quarterLength=0) to a quarter rest.
        if ql < 1e-6:
            return None
        return m21note.Rest(quarterLength=ql)

    @staticmethod
    def _safe_insert(container, offset, obj) -> bool:
        """Insert only real music21 objects.

        ``Stream.insert(0, None)`` is parsed as one-arg ``insert(0)`` and raises
        ``Cannot insert item 0 to stream -- is it a music21 object?``.
        """
        if obj is None or not isinstance(obj, Music21Object):
            return False
        container.insert(offset, obj)
        return True

    @staticmethod
    def _safe_append(container, obj) -> bool:
        if obj is None or not isinstance(obj, Music21Object):
            return False
        container.append(obj)
        return True

    def _fit_stream_to_quarter_length(
        self,
        container,
        mql: float,
        measure_number: int | None = None,
        staff_id: int | None = None,
        voice_id: int | None = None,
    ) -> int:
        """Last-resort bar clamp. Valid plans must not need this.

        Overflow is logged rather than silently deleting musical material.
        """
        mql = float(mql or 0.0)
        if mql <= 1e-8:
            return 0
        overflow = float(container.highestTime) - mql
        if overflow <= 1e-6:
            return 0
        trimmed = 0
        for el in reversed(list(container.notesAndRests)):
            if overflow <= 1e-6:
                break
            ql = float(el.quarterLength or 0.0)
            cls = type(el).__name__
            if ql <= overflow + 1e-9:
                container.remove(el)
                overflow -= ql
                trimmed += 1
                log_notation_invariant(
                    "TRIM",
                    job_id=self.last_job_id,
                    measure=measure_number,
                    staff=staff_id,
                    voice=voice_id,
                    element=cls,
                    duration=ql,
                    measure_length=mql,
                    action="remove",
                )
                continue
            el.quarterLength = ql - overflow
            trimmed += 1
            log_notation_invariant(
                "TRIM",
                job_id=self.last_job_id,
                measure=measure_number,
                staff=staff_id,
                voice=voice_id,
                element=cls,
                duration=ql,
                end=ql - overflow,
                measure_length=mql,
                action="shorten",
            )
            overflow = 0.0
            if float(el.quarterLength) <= 1e-8:
                container.remove(el)
        if not list(container.notesAndRests):
            rest = m21note.Rest(quarterLength=mql)
            self._safe_append(container, rest)
        self.last_fit_trim_count += trimmed
        return trimmed

    def build_score(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        quantize_divisors: tuple[int, ...] = (4, 3),
        fallback_bpm: float = 120.0,
        quantization_mode: QuantizationMode | str | None = None,
    ) -> stream.Score:
        mode = (
            parse_quantization_mode(quantization_mode)
            if quantization_mode is not None
            else self.last_quantization_mode
        )
        quantized = (
            list(events)
            if quantization_skips_legacy_grid(mode)
            else quantize_events(events, quantize_divisors)
        )
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
        self._safe_insert(score, 0, md)
        self._safe_insert(score, 0, rh)
        self._safe_insert(score, 0, lh)
        group = layout.StaffGroup(
            [rh, lh],
            name="Piano",
            abbreviation="Pno.",
            symbol="brace",
            barTogether=True,
        )
        self._safe_insert(score, 0, group)
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
        self._safe_insert(part, 0, instrument.Piano())
        self._safe_insert(part, 0, staff_clef)
        self._safe_insert(part, 0, self._time_signature(ts_str))
        if key_name:
            self._safe_insert(part, 0, self._key_signature(key_name))

        for start, group in _chord_clusters(events):
            self._safe_insert(part, start, self._m21_element(group))

        if not events:
            rest = self._rest_for_length(max(end_beat, 1.0))
            if rest is not None:
                self._safe_insert(part, 0, rest)
        return part

    def _m21_element(self, group: list[MusicalEvent]):
        if not group:
            return None
        duration = max(float(e.duration_beats or 0.0) for e in group)
        if duration <= 1e-8:
            return None
        pitches: list[int] = []
        for ev in group:
            try:
                midi = int(ev.pitch)
            except (TypeError, ValueError):
                continue
            if 0 <= midi <= 127:
                pitches.append(midi)
        if not pitches:
            return self._rest_for_length(duration)
        if len(pitches) == 1:
            el = m21note.Note(midi=pitches[0])
            el.volume.velocity = max(1, min(127, int(group[0].velocity)))
        else:
            el = m21chord.Chord(pitches)
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
        quantization_mode: QuantizationMode | str | None = None,
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
        mode = (
            parse_quantization_mode(quantization_mode)
            if quantization_mode is not None
            else self.last_quantization_mode
        )
        if not quantization_skips_legacy_grid(mode):
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

    def _apply_tempo_map(self, score, meta: ScoreMeta, score_beat_offset: float = 0.0) -> None:
        if (meta.extra or {}).get("preserve_midi_tempo") and meta.tempo_map is not None:
            for pt in meta.tempo_map.sorted_points():
                beat = meta.tempo_map.seconds_to_beats(pt.time_sec) + score_beat_offset
                if 0 <= beat < float(score.highestTime):
                    self._insert_metronome_at_beat(score, beat, float(pt.bpm))
            return
        printed = (meta.extra or {}).get("printed_tempo")
        if self.last_quantization_mode == QuantizationMode.PERFORMANCE and printed is not None:
            # MusicalTimeMap handles performed rubato. Only sustained tempo
            # regions belong on the page, using the same score-beat origin.
            for annotation in printed:
                bpm = annotation.get("bpm")
                if annotation.get("mark") == "a_tempo":
                    bpm = meta.display_tempo_bpm
                beat = float(annotation.get("beat", 0.0))
                if bpm and 0 <= beat < float(score.highestTime):
                    self._insert_metronome_at_beat(score, beat, int(round(bpm)))
            return
        tempo_map: TempoMap | None = meta.tempo_map
        if tempo_map is None or len(tempo_map.sorted_points()) < 2:
            return
        from transcription import snap_to_standard_tempo

        last_bpm = float(meta.display_tempo_bpm or 120)
        snap = quantization_snaps_display_tempo(self.last_quantization_mode)
        for pt in tempo_map.sorted_points():
            if pt.time_sec <= 1e-6:
                continue
            next_bpm = (
                float(snap_to_standard_tempo(pt.bpm)) if snap else float(pt.bpm)
            )
            if abs(next_bpm - last_bpm) / max(last_bpm, 1.0) < 0.08:
                continue
            offset = tempo_map.seconds_to_beats(pt.time_sec) + score_beat_offset
            if offset <= 0:
                continue
            self._insert_metronome_at_beat(score, offset, int(round(next_bpm)))
            last_bpm = next_bpm

    def _insert_metronome_at_beat(self, score, beat: float, bpm: float) -> None:
        """Put a metronome mark inside the measure that OSMD/MusicXML will export."""
        mark = m21tempo.MetronomeMark(number=float(bpm))
        try:
            mark.placement = "above"
        except Exception:
            pass
        part = score.parts[0] if getattr(score, "parts", None) else score
        try:
            measures = list(part.getElementsByClass("Measure"))
        except Exception:
            measures = []
        if not measures:
            self._safe_insert(part, max(0.0, float(beat)), mark)
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
                    existing[0].number = float(bpm)
                    return
                self._safe_insert(meas, local, mark)
                return
        first = measures[0]
        existing = list(first.getElementsByClass(m21tempo.MetronomeMark))
        if existing:
            existing[0].number = float(bpm)
            return
        self._safe_insert(first, 0, mark)

    def _export_musicxml(self, score, xml_path: Path) -> None:
        self._sanitize_export_durations(score)
        try:
            score.write("musicxml", fp=str(xml_path))
        except Exception as exc:
            print(
                f"[Notation] MusicXML write failed ({exc!s}); "
                "retrying without makeNotation"
            )
            self._sanitize_export_durations(score)
            score.write("musicxml", fp=str(xml_path), makeNotation=False)
        xml = xml_path.read_text(encoding="utf-8")
        cleaned = _strip_forced_musicxml_layout(xml)
        if cleaned != xml:
            xml_path.write_text(cleaned, encoding="utf-8")

    def _sanitize_export_durations(self, score) -> None:
        """Replace MusicXML-inexpressible durations and trim voices to the bar."""
        if self.last_quantization_mode == QuantizationMode.PERFORMANCE:
            for element in score.recurse().notesAndRests:
                if element.quarterLength <= 0 or element.duration.type in (None, "inexpressible", "complex", ""):
                    raise ValueError("Performance plan contains an unspellable duration")
            if self.last_fit_trim_count:
                raise ValueError("Performance plan required destructive bar fitting")
            return
        victims = []
        for n in score.recurse().notesAndRests:
            ql = float(getattr(n, "quarterLength", 0.0) or 0.0)
            dtype = getattr(getattr(n, "duration", None), "type", None)
            if ql <= 1e-8:
                victims.append(n)
                continue
            if dtype in (None, "inexpressible", "complex", ""):
                snapped = snap_writable_length(ql, allow_empty=True)
                if snapped <= 1e-9:
                    victims.append(n)
                else:
                    n.quarterLength = snapped
        for n in victims:
            site = n.activeSite
            if site is None:
                continue
            try:
                site.remove(n)
            except Exception:
                pass
        for voice in score.recurse().getElementsByClass(stream.Voice):
            measure = voice.getContextByClass(stream.Measure)
            mql = 4.0
            if measure is not None:
                try:
                    mql = float(measure.barDuration.quarterLength)
                except Exception:
                    mql = float(getattr(measure.duration, "quarterLength", 4.0) or 4.0)
            self._fit_stream_to_quarter_length(voice, mql)
            if not list(voice.notesAndRests):
                rest = self._rest_for_length(mql)
                self._safe_append(voice, rest)


def iter_invalid_stream_objects(score) -> list[tuple[str, object]]:
    """Return (site, obj) pairs that are not music21 objects."""
    bad: list[tuple[str, object]] = []
    try:
        sites = [score, *score.recurse()]
    except Exception:
        sites = [score]
    for site in sites:
        try:
            children = list(site)
        except Exception:
            continue
        site_name = type(site).__name__
        for child in children:
            if child is None or not isinstance(child, Music21Object):
                bad.append((site_name, child))
    return bad


def _strip_forced_musicxml_layout(xml: str) -> str:
    """Remove explicit system/page breaks and measure widths.

    OSMD packs measures from available page width. Forced MusicXML breaks
    produce one-bar-per-line scores even when the music is short.
    """
    cleaned = re.sub(r'\snew-system="yes"', "", xml, flags=re.IGNORECASE)
    cleaned = re.sub(r'\snew-page="yes"', "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"<system-layout>[\s\S]*?</system-layout>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<page-layout>[\s\S]*?</page-layout>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r'(<measure\b[^>]*?)\s+width="[^"]*"',
        r"\1",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


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
