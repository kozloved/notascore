"""Music Understanding pipeline orchestrator (canonical path)."""

from __future__ import annotations

import os
from pathlib import Path

from adapters.basic_pitch_backend import BasicPitchBackend
from adapters.classical_dsp_backend import ClassicalDspBackend
from adapters.mt3_backend import MT3Backend
from audio_engine.chord_detector import ChordDetector
from audio_engine.instrument_classifier import InstrumentClassifier
from audio_engine.normalizer import AudioNormalizer
from audio_engine.piano_analyzer import PianoAudioAnalyzer
from audio_engine.role_separator import MelodyAccompanimentSeparator
from audio_engine.segmenter import AudioSegmenter
from mir.articulation import ArticulationDetector
from mir.cmr_builder import build_score_meta, notes_to_events
from mir.debug import PipelineDebug
from mir.dynamics import DynamicsExtractor
from mir.hand_separator import HandSeparator
from mir.meter import MeterEstimator
from mir.midi_cleaner import MIDICleaner
from mir.models import (
    CleaningAction,
    MusicalStructure,
    PedalObservation,
    RawPerformance,
    TempoObservation,
    TranscriptionResult,
)
from mir.phrase_detector import PhraseDetector
from mir.types import InstrumentKind, MusicalEvent, NoteEvent, TempoMap, TempoPoint
from mir.voice_separator import VoiceSeparator
from notation_engine.writer import NotationWriter
from transcription import (
    QUANTIZE_DIVISORS,
    TranscriptionError,
    _env_enabled,
    _estimate_tempo,
    snap_to_standard_tempo,
)


def get_backend(name: str | None = None):
    backend = (name or os.getenv("TRANSCRIPTION_BACKEND", "basic_pitch")).lower()
    if backend == "classical_dsp":
        return ClassicalDspBackend()
    if backend == "mt3":
        return MT3Backend()
    return BasicPitchBackend()


class UnderstandingPipeline:
    """Audio → RawPerformance → MusicalStructure → NotationPlan → MusicXML."""

    name = "understanding"

    def __init__(self, use_mir_layers: bool | None = None, mode: str = "fast"):
        self.normalizer = AudioNormalizer()
        self.classifier = InstrumentClassifier()
        self.segmenter = AudioSegmenter()
        self.cleaner = MIDICleaner()
        self.piano_analyzer = PianoAudioAnalyzer()
        self.chord_detector = ChordDetector()
        self.role_separator = MelodyAccompanimentSeparator()
        self.hand_separator = HandSeparator()
        self.voice_separator = VoiceSeparator()
        self.dynamics = DynamicsExtractor()
        self.articulation = ArticulationDetector()
        self.phrase_detector = PhraseDetector()
        self.meter_estimator = MeterEstimator()
        self.notation = NotationWriter()
        self.mode = mode
        if use_mir_layers is None:
            use_mir_layers = _env_enabled("TRANSCRIPTION_USE_MIR_LAYERS", default=True)
        self.use_mir_layers = use_mir_layers
        self.last_debug: PipelineDebug | None = None
        self.last_structure: MusicalStructure | None = None

    def transcribe(self, audio_path: str | Path, job_id: str) -> str:
        audio_path = Path(audio_path)
        normalized = self.normalizer.normalize(audio_path)
        prediction = self.classifier.classify(normalized)
        segments = self.segmenter.segment(normalized)

        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)
        transcribe_path = self.normalizer.write_wav(
            normalized, out_dir / f"{job_id}_norm.wav"
        )

        backend = get_backend()
        notes = [
            n.ensure_ids(i)
            for i, n in enumerate(backend.transcribe_notes(transcribe_path))
        ]
        notes = [
            NoteEvent(
                pitch=n.pitch,
                start_time=n.start_time,
                end_time=n.end_time,
                velocity=n.velocity,
                confidence=n.confidence,
                note_id=n.note_id or f"n{i:04d}",
                source_backend=n.source_backend or backend.name,
                original_start_time=n.original_start_time
                if n.original_start_time is not None
                else n.start_time,
                original_end_time=n.original_end_time
                if n.original_end_time is not None
                else n.end_time,
            )
            for i, n in enumerate(notes)
        ]
        raw_count = len(notes)
        transcription = TranscriptionResult(
            notes=list(notes),
            backend=backend.name,
            audio_path=str(transcribe_path),
        )

        if not notes:
            raise TranscriptionError("No notes detected")

        notes, clean_decisions = self.cleaner.clean_with_report(notes)
        print(
            f"[MIDICleaner] notes {raw_count} → {len(notes)} (job={job_id})"
        )

        pedal_events: list[PedalObservation] = []
        if prediction.instrument == InstrumentKind.PIANO:
            piano = self.piano_analyzer.analyze(normalized, notes)
            notes = piano.notes
            pedal_events = [
                PedalObservation(
                    time_sec=p.time_sec, value=p.value, confidence=p.confidence
                )
                for p in piano.pedal_events
            ]
            print(
                f"[PianoAnalyzer] refined velocities for {len(notes)} notes "
                f"(job={job_id})"
            )

        onsets = [n.start_time for n in notes]
        bpm = _estimate_tempo(audio_path, onsets)
        tempo_map = TempoMap(
            points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=bpm, confidence=0.9)]
        )

        performance = RawPerformance(
            notes=list(transcription.notes),
            pedal_events=pedal_events,
            tempo_observations=[
                TempoObservation(
                    time_sec=0.0, bpm=bpm, confidence=0.9, source="beat_refine"
                )
            ],
            source_backend=backend.name,
            source_path=str(audio_path),
        )
        self._write_raw_midi(performance.notes, bpm, out_dir / f"{job_id}.raw.mid")

        chords = self.chord_detector.detect(notes)
        role = self.role_separator.separate(notes)

        events = notes_to_events(
            notes,
            tempo_map,
            role=role,
            instrument=prediction.instrument,
            source_backend=backend.name,
        )

        if self.use_mir_layers:
            events = self.hand_separator.separate(events)
            events = self.voice_separator.separate(events)
            events = self.dynamics.extract(events)
            events = self.articulation.detect(events)
            phrase_map = self.phrase_detector.detect_from_notes(notes, bpm=bpm)
            events = self.phrase_detector.apply(events, phrase_map, bpm=bpm)

        meter_hyps = self.meter_estimator.estimate(events)
        selected_meter = meter_hyps[0]
        structure = MusicalStructure(
            events=events,
            tempo_map=tempo_map,
            meter_hypotheses=meter_hyps,
            selected_meter=selected_meter,
            instrument=prediction.instrument,
            instrument_confidence=prediction.confidence,
            instrument_prediction=prediction,
            segments=list(segments),
            extra={"chords": [c.name for c in chords[:12]]},
        )
        self.last_structure = structure

        meta = build_score_meta(
            tempo_map,
            prediction.instrument,
            segments,
            display_bpm=snap_to_standard_tempo(bpm),
            instrument_confidence=prediction.confidence,
        )
        meta.time_sig_hint = selected_meter.time_signature

        hand_counts = {"left": 0, "right": 0, "unknown": 0, "ambiguous": 0}
        voice_counts: dict[str, int] = {}
        for ev in events:
            hand_counts[ev.hand.value] = hand_counts.get(ev.hand.value, 0) + 1
            key = f"{ev.hand.value}:{ev.voice}"
            voice_counts[key] = voice_counts.get(key, 0) + 1

        debug = PipelineDebug(
            job_id=job_id,
            pipeline="understanding",
            transcription_mode=self.mode,
            source_backend=backend.name,
            raw_note_count=raw_count,
            cleaned_note_count=len(notes),
            removed_notes=[
                {
                    "note_id": d.note_id,
                    "pitch": d.pitch,
                    "action": d.action.value,
                    "reason": d.reason,
                    "evidence": d.evidence,
                }
                for d in clean_decisions
                if d.action == CleaningAction.SUPPRESS
            ],
            uncertain_notes=[
                {
                    "note_id": d.note_id,
                    "pitch": d.pitch,
                    "reason": d.reason,
                    "evidence": d.evidence,
                }
                for d in clean_decisions
                if d.action == CleaningAction.UNCERTAIN
            ],
            detected_instrument=prediction.instrument.value,
            instrument_confidence=prediction.confidence,
            tempo_hypotheses=[{"bpm": bpm, "source": "beat_refine"}],
            selected_tempo_bpm=bpm,
            selected_meter=selected_meter.time_signature,
            meter_confidence=selected_meter.confidence,
            hand_assignments=hand_counts,
            voice_assignments=voice_counts,
            extra={"role_confidence": role.confidence},
        )
        self.last_debug = debug
        debug.write_json(out_dir / f"{job_id}.debug.json")

        print(
            f"[Understanding] instrument={prediction.instrument.value} "
            f"tempo={bpm:.1f} meter={selected_meter.time_signature} "
            f"events={len(events)} mir_layers={self.use_mir_layers} "
            f"(job={job_id})"
        )

        return self.notation.write_musicxml(
            events,
            meta,
            job_id=job_id,
            audio_path=audio_path,
            quantize_divisors=QUANTIZE_DIVISORS,
            fallback_bpm=bpm,
            structure=structure,
        )

    @staticmethod
    def _write_raw_midi(notes: list[NoteEvent], bpm: float, path: Path) -> None:
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        inst = pretty_midi.Instrument(program=0, name="raw")
        for n in notes:
            inst.notes.append(
                pretty_midi.Note(
                    velocity=n.velocity,
                    pitch=n.pitch,
                    start=n.start_time,
                    end=n.end_time,
                )
            )
        midi.instruments.append(inst)
        midi.write(str(path))

    @staticmethod
    def notes_from_events(events: list[MusicalEvent], bpm: float) -> list[NoteEvent]:
        """Convert events back to seconds for testing."""
        spb = 60.0 / bpm
        return [
            NoteEvent(
                pitch=e.pitch,
                start_time=e.start_beat * spb,
                end_time=(e.start_beat + e.duration_beats) * spb,
                velocity=e.velocity,
                confidence=e.confidence,
                note_id=e.note_id,
                source_backend=e.source_backend,
            )
            for e in events
        ]
