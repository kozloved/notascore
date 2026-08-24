"""Write MusicXML from a NotationPlan (music21 is an export library)."""

from __future__ import annotations

from pathlib import Path

import pretty_midi
from music21 import (
    articulations,
    chord as m21chord,
    clef as m21clef,
    dynamics as m21dyn,
    key as m21key,
    layout,
    meter as m21meter,
    note as m21note,
    stream,
    tempo as m21tempo,
    tie as m21tie,
)

from mir.models import NotationPlan, PlannedNote, PlannedRest
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner


class NotationWriter:
    """Convert CMR events / a NotationPlan to MusicXML via music21."""

    def __init__(self):
        self.planner = NotationPlanner()

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

        bpm = meta.display_tempo_bpm or int(fallback_bpm)
        self._events_to_midi(events, bpm, out_dir / f"{job_id}.mid")

        plan, _decisions = self.planner.build(
            events, meta=meta, structure=structure, fallback_bpm=fallback_bpm
        )
        score = self.score_from_plan(plan)

        xml_path = out_dir / f"{job_id}.musicxml"
        score.write("musicxml", fp=str(xml_path))
        return xml_path.read_text(encoding="utf-8")

    def write_from_events_direct(
        self, events: list[MusicalEvent], meta: ScoreMeta
    ) -> stream.Score:
        """Build music21 score without MIDI round-trip (for tests)."""
        bpm = meta.display_tempo_bpm or 120
        s = stream.Score()
        s.insert(0, m21tempo.MetronomeMark(number=bpm))
        part = stream.Part()
        for ev in events:
            n = m21note.Note(ev.pitch)
            n.quarterLength = max(0.25, ev.duration_beats)
            part.insert(ev.start_beat, n)
        s.insert(0, part)
        return s

    def write_from_plan(self, plan: NotationPlan) -> stream.Score:
        return self.score_from_plan(plan)

    def score_from_plan(self, plan: NotationPlan) -> stream.Score:
        score = stream.Score()
        score.insert(0, m21tempo.MetronomeMark(number=plan.tempo_bpm))

        n_staves = 0
        for measure in plan.measures:
            for staff in measure.staves:
                n_staves = max(n_staves, staff.staff_id + 1)
        n_staves = max(1, n_staves)

        parts: list[stream.Part] = []
        for sid in range(n_staves):
            part = stream.Part(id=f"P{sid + 1}")
            name = "Right Hand" if sid == 0 else "Left Hand"
            if n_staves == 1:
                name = "Music"
            part.partName = name
            part.partAbbreviation = "RH" if sid == 0 else "LH"
            parts.append(part)
            score.insert(0, part)

        if n_staves >= 2:
            group = layout.StaffGroup(
                parts[:2],
                name="Piano",
                abbreviation="Pno.",
                symbol="brace",
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
                    m.insert(0, m21meter.TimeSignature(plan.time_signature))
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
            return m21clef.BassClef()
        return m21clef.TrebleClef()

    def _events_to_midi(
        self, events: list[MusicalEvent], bpm: float, path: Path
    ) -> Path:
        midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        rh = pretty_midi.Instrument(program=0, name="RH")
        lh = pretty_midi.Instrument(program=0, name="LH")
        spb = 60.0 / bpm

        for ev in events:
            inst = lh if ev.hand == Hand.LEFT else rh
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
            inst = pretty_midi.Instrument(program=0)
            for ev in events:
                inst.notes.append(
                    pretty_midi.Note(
                        velocity=ev.velocity,
                        pitch=ev.pitch,
                        start=ev.start_beat * spb,
                        end=(ev.start_beat + ev.duration_beats) * spb,
                    )
                )
            midi.instruments.append(inst)

        midi.write(str(path))
        return path
