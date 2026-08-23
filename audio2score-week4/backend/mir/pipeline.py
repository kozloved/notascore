"""Music Understanding pipeline orchestrator."""

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
from mir.phrase_detector import PhraseDetector
from mir.articulation import ArticulationDetector
from mir.cmr_builder import build_score_meta, notes_to_events
from mir.dynamics import DynamicsExtractor
from mir.hand_separator import HandSeparator
from mir.midi_cleaner import MIDICleaner
from mir.types import InstrumentKind, MusicalEvent, NoteEvent, ScoreMeta, TempoMap
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
    """Audio → CMR → MIR → MusicXML."""

    name = "understanding"

    def __init__(self, use_mir_layers: bool | None = None):
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
        self.notation = NotationWriter()
        if use_mir_layers is None:
            use_mir_layers = _env_enabled("TRANSCRIPTION_USE_MIR_LAYERS", default=True)
        self.use_mir_layers = use_mir_layers

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
        notes = backend.transcribe_notes(transcribe_path)
        raw_count = len(notes)

        if not notes:
            raise TranscriptionError("No notes detected")

        notes = self.cleaner.clean(notes)
        print(
            f"[MIDICleaner] notes {raw_count} → {len(notes)} (job={job_id})"
        )

        if prediction.instrument == InstrumentKind.PIANO:
            piano = self.piano_analyzer.analyze(normalized, notes)
            notes = piano.notes
            print(
                f"[PianoAnalyzer] refined velocities for {len(notes)} notes "
                f"(job={job_id})"
            )

        onsets = [n.start_time for n in notes]
        bpm = _estimate_tempo(audio_path, onsets)
        from mir.types import TempoPoint

        tempo_map = TempoMap(
            points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=bpm, confidence=0.9)]
        )

        self.chord_detector.detect(notes)
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

        meta = build_score_meta(
            tempo_map,
            prediction.instrument,
            segments,
            display_bpm=snap_to_standard_tempo(bpm),
        )

        print(
            f"[Understanding] instrument={prediction.instrument.value} "
            f"tempo={bpm:.1f} events={len(events)} mir_layers={self.use_mir_layers} "
            f"(job={job_id})"
        )

        return self.notation.write_musicxml(
            events,
            meta,
            job_id=job_id,
            audio_path=audio_path,
            quantize_divisors=QUANTIZE_DIVISORS,
            fallback_bpm=bpm,
        )

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
            )
            for e in events
        ]
