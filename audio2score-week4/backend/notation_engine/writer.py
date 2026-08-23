"""Write MusicXML from MusicalEvent[] (source-agnostic)."""

from __future__ import annotations

from pathlib import Path

import pretty_midi
from music21 import converter, note as m21note, stream, tempo as m21tempo

from mir.types import Hand, MusicalEvent, ScoreMeta


class NotationWriter:
    """Convert CMR events to MusicXML via music21."""

    def write_musicxml(
        self,
        events: list[MusicalEvent],
        meta: ScoreMeta,
        job_id: str,
        audio_path: Path,
        quantize_divisors: tuple[int, ...] = (4, 3),
        fallback_bpm: float = 120.0,
    ) -> str:
        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)

        bpm = meta.display_tempo_bpm or int(fallback_bpm)
        midi_path = self._events_to_midi(events, bpm, out_dir / f"{job_id}.mid")

        score = converter.parse(str(midi_path))
        score.quantize(
            quarterLengthDivisors=quantize_divisors,
            processOffsets=True,
            processDurations=True,
            inPlace=True,
            recurse=True,
        )

        marks = list(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
        if marks:
            for mark in marks:
                mark.number = bpm
        else:
            score.insert(0, m21tempo.MetronomeMark(number=bpm))

        self._apply_dynamics(score, events)
        self._apply_articulations(score, events)

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

    def _events_to_midi(
        self, events: list[MusicalEvent], bpm: float, path: Path
    ) -> Path:
        midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        rh = pretty_midi.Instrument(program=0, name="RH")
        lh = pretty_midi.Instrument(program=0, name="LH")
        spb = 60.0 / bpm

        for ev in events:
            inst = lh if ev.hand.value == "left" else rh
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

    def _apply_dynamics(self, score, events: list[MusicalEvent]) -> None:
        from music21 import dynamics as m21dyn

        dynamic_map = {e.pitch: e.dynamic for e in events if e.dynamic}
        for el in score.recurse().notes:
            if hasattr(el, "pitch") and el.pitch.midi in dynamic_map:
                mark = dynamic_map[el.pitch.midi]
                if mark in ("p", "pp", "mp", "mf", "f", "ff"):
                    el.expressions.append(m21dyn.Dynamic(mark))

    def _apply_articulations(self, score, events: list[MusicalEvent]) -> None:
        from music21 import articulations

        art_map = {
            (e.pitch, round(e.start_beat, 3)): e.articulation
            for e in events
            if e.articulation
        }
        for el in score.recurse().notes:
            if not hasattr(el, "pitch"):
                continue
            key = (el.pitch.midi, round(float(el.offset), 3))
            art = art_map.get(key)
            if art == "staccato":
                el.articulations.append(articulations.Staccato())
            elif art == "legato":
                el.articulations.append(articulations.Tenuto())
