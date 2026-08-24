"""Music Understanding pipeline orchestrator."""

from __future__ import annotations

import os
from pathlib import Path

from adapters.basic_pitch_backend import BasicPitchBackend
from adapters.classical_dsp_backend import ClassicalDspBackend
from adapters.mt3_backend import MT3Backend
from audio_engine.beat_tracker import (
    BeatTracker,
    align_tempo_map,
    constant_tempo_map,
)
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
from mir.midi_ingest import ingest_midi, is_midi_path
from mir.raw_midi import job_raw_midi_path, write_job_raw_midi
from mir.types import MusicalEvent, NoteEvent, TempoMap
from mir.voice_separator import VoiceSeparator
from notation_engine.writer import NotationWriter
from transcription import (
    QUANTIZE_DIVISORS,
    TranscriptionError,
    _env_enabled,
    _should_analyze_piano,
    _use_beat_tracker,
    detect_tempo,
    refine_tempo,
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

    def __init__(
        self,
        use_mir_layers: bool | None = None,
        backend_name: str | None = None,
    ):
        self.backend_name = backend_name
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
        self.beat_tracker = BeatTracker()
        if use_mir_layers is None:
            use_mir_layers = _env_enabled("TRANSCRIPTION_USE_MIR_LAYERS", default=True)
        self.use_mir_layers = use_mir_layers

    def transcribe(self, audio_path: str | Path, job_id: str) -> str:
        audio_path = Path(audio_path)
        if is_midi_path(audio_path):
            return self.transcribe_midi(audio_path, job_id)

        normalized = self.normalizer.normalize(audio_path)
        prediction = self.classifier.classify(normalized)
        segments = self.segmenter.segment(normalized)

        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)
        transcribe_path = self.normalizer.write_wav(
            normalized, out_dir / f"{job_id}_norm.wav"
        )

        backend = get_backend(self.backend_name)
        notes = backend.transcribe_notes(transcribe_path)
        raw_count = len(notes)

        if not notes:
            raise TranscriptionError("No notes detected")

        notes = self.cleaner.clean(notes)
        print(
            f"[MIDICleaner] notes {raw_count} → {len(notes)} (job={job_id})"
        )

        pedal_events: list[tuple[float, int]] = []
        if _should_analyze_piano(prediction.instrument):
            piano = self.piano_analyzer.analyze(normalized, notes)
            notes = piano.notes
            pedal_events = [(p.time_sec, p.value) for p in piano.pedal_events]
            print(
                f"[PianoAnalyzer] refined velocities for {len(notes)} notes "
                f"pedal={len(pedal_events)} (job={job_id})"
            )

        onsets = [n.start_time for n in notes]
        tempo_map, meter = self._build_tempo_map(normalized, audio_path, onsets)
        bpm = tempo_map.bpm_at(0.0)

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
            events = self.phrase_detector.assign(events)

        meta = build_score_meta(
            tempo_map,
            prediction.instrument,
            segments,
            display_bpm=snap_to_standard_tempo(bpm),
            time_sig_hint=meter,
        )

        def _rebuild(next_notes, next_tempo, next_role):
            rebuilt = notes_to_events(
                next_notes,
                next_tempo,
                role=next_role,
                instrument=prediction.instrument,
                source_backend=backend.name,
            )
            if self.use_mir_layers:
                rebuilt = self.hand_separator.separate(rebuilt)
                rebuilt = self.voice_separator.separate(rebuilt)
                rebuilt = self.dynamics.extract(rebuilt)
                rebuilt = self.articulation.detect(rebuilt)
                rebuilt = self.phrase_detector.assign(rebuilt)
            return rebuilt

        from intelligence.layer import maybe_enhance

        enhanced = maybe_enhance(
            job_id=job_id,
            notes=notes,
            events=events,
            meta=meta,
            tempo_map=tempo_map,
            prediction=prediction,
            chords=chords,
            normalized=normalized,
            pedal_events=pedal_events,
            role=role,
            rebuild_events=_rebuild,
        )
        notes = enhanced.notes
        events = enhanced.events
        meta = enhanced.meta
        tempo_map = enhanced.tempo_map
        bpm = tempo_map.bpm_at(0.0)

        print(
            f"[Understanding] instrument={prediction.instrument.value} "
            f"tempo={bpm:.1f} meter={meta.time_sig_hint or '-'} "
            f"tempo_points={len(tempo_map.points)} "
            f"events={len(events)} mir_layers={self.use_mir_layers} "
            f"(job={job_id})"
        )

        write_job_raw_midi(
            audio_path,
            job_id,
            notes,
            bpm=bpm,
            events=events if events else None,
            pedal_events=pedal_events,
            tempo_map=tempo_map,
        )

        return self.notation.write_musicxml(
            events,
            meta,
            job_id=job_id,
            audio_path=audio_path,
            quantize_divisors=QUANTIZE_DIVISORS,
            fallback_bpm=bpm,
        )

    def transcribe_midi(self, midi_path: str | Path, job_id: str) -> str:
        """CMR entry for an uploaded MIDI file (no Basic Pitch)."""
        import shutil

        from mir.types import InstrumentKind

        midi_path = Path(midi_path)
        ingested = ingest_midi(midi_path)
        notes = ingested.notes
        tempo_map = ingested.tempo_map
        bpm = tempo_map.bpm_at(0.0)

        out_dir = midi_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)
        raw_path = job_raw_midi_path(midi_path, job_id)
        if midi_path.resolve() != raw_path.resolve():
            shutil.copy2(midi_path, raw_path)

        role = self.role_separator.separate(notes)
        events = notes_to_events(
            notes,
            tempo_map,
            role=role,
            instrument=InstrumentKind.PIANO,
            source_backend="midi",
        )
        if self.use_mir_layers:
            events = self.hand_separator.separate(events)
            events = self.voice_separator.separate(events)
            events = self.dynamics.extract(events)
            events = self.articulation.detect(events)
            events = self.phrase_detector.assign(events)

        meta = build_score_meta(
            tempo_map,
            InstrumentKind.PIANO,
            [],
            display_bpm=snap_to_standard_tempo(bpm),
            time_sig_hint=ingested.time_sig_hint,
        )
        from intelligence.layer import maybe_enhance
        from mir.types import InstrumentPrediction

        midi_pred = InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9)

        def _rebuild(next_notes, next_tempo, next_role):
            rebuilt = notes_to_events(
                next_notes,
                next_tempo,
                role=next_role,
                instrument=InstrumentKind.PIANO,
                source_backend="midi",
            )
            if self.use_mir_layers:
                rebuilt = self.hand_separator.separate(rebuilt)
                rebuilt = self.voice_separator.separate(rebuilt)
                rebuilt = self.dynamics.extract(rebuilt)
                rebuilt = self.articulation.detect(rebuilt)
                rebuilt = self.phrase_detector.assign(rebuilt)
            return rebuilt

        enhanced = maybe_enhance(
            job_id=job_id,
            notes=notes,
            events=events,
            meta=meta,
            tempo_map=tempo_map,
            prediction=midi_pred,
            chords=None,
            normalized=None,
            pedal_events=ingested.pedal_events if hasattr(ingested, "pedal_events") else None,
            role=role,
            rebuild_events=_rebuild,
        )
        notes = enhanced.notes
        events = enhanced.events
        meta = enhanced.meta
        tempo_map = enhanced.tempo_map
        bpm = tempo_map.bpm_at(0.0)
        print(
            f"[MidiIngest] notes={len(notes)} tempo={bpm:.1f} "
            f"tempo_points={len(tempo_map.points)} events={len(events)} "
            f"(job={job_id})"
        )
        return self.notation.write_musicxml(
            events,
            meta,
            job_id=job_id,
            audio_path=midi_path,
            quantize_divisors=QUANTIZE_DIVISORS,
            fallback_bpm=bpm,
        )

    def _build_tempo_map(
        self, normalized, audio_path, onsets: list[float]
    ) -> tuple[TempoMap, str | None]:
        if _use_beat_tracker():
            tracked = self.beat_tracker.track_stable(normalized)
            meter = self.beat_tracker.last_time_signature
            source = self.beat_tracker.last_source
            seed = tracked.bpm_at(0.0)
            # madmom already owns the beat grid; MIDI-onset refine was for librosa
            # octave errors and can pull a good map toward 76/90 on sparse notes.
            if source == "madmom":
                return tracked, meter
            refined = refine_tempo(onsets, seed)
            return align_tempo_map(tracked, refined), meter
        seed = detect_tempo(audio_path)
        return constant_tempo_map(refine_tempo(onsets, seed)), None

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
