"""Music Understanding pipeline orchestrator (canonical path)."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
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
from mir.articulation import ArticulationDetector
from mir.cmr_builder import build_score_meta, notes_to_events
from mir.debug import PipelineDebug
from mir.dynamics import DynamicsExtractor
from mir.hand_separator import build_hand_separator
from mir.job import ImmutableNoteSet, PipelineJob
from mir.meter import MeterEstimator
from mir.meter_arbitrator import BeatGroupingEvidence, MeterArbitrator
from mir.midi_cleaner import MIDICleaner
from mir.midi_ingest import ingest_midi, is_midi_path
from mir.performance import PerformanceSnapshot
from mir.models import (
    CleaningAction,
    MeterDecision,
    MusicalStructure,
    PedalObservation,
    RawPerformance,
    TempoObservation,
    TranscriptionResult,
)
from mir.phrase_detector import PhraseDetector
from mir.pipeline_config import (
    PipelineConfig,
    QuantizationMode,
    load_pipeline_config,
    piano_analysis_enabled,
    quantization_snaps_display_tempo,
)
from mir.raw_identity import record_saved_raw
from mir.raw_midi import (
    job_raw_midi_path,
    job_validated_midi_path,
    write_job_stage_midi,
)
from mir.types import InstrumentKind, MusicalEvent, NoteEvent, TempoMap
from mir.voice_separator import VoiceSeparator
from notation_engine.writer import NotationWriter
from timing.service import (
    align_score_origin,
    apply_score_time_map,
    resolve_from_existing_tracker,
    resolve_from_tempo_map,
    score_time_consistency_issues,
)
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


@dataclass
class PreparedAudio:
    """Normalized audio + selected backend. Beat tracking still happens once later."""

    audio_path: Path
    job_id: str
    normalized: object
    transcribe_path: Path
    backend: object
    out_dir: Path


class UnderstandingPipeline:
    """Audio → RawPerformance → MusicalStructure → NotationPlan → MusicXML."""

    name = "understanding"

    def __init__(
        self,
        use_mir_layers: bool | None = None,
        backend_name: str | None = None,
        mode: str = "solo",
        validation_mode: str | None = None,
    ):
        self.backend_name = backend_name
        self.mode = mode
        self._validation_override = validation_mode
        self.config: PipelineConfig = load_pipeline_config(
            backend=backend_name, mode=mode, validation_mode=validation_mode
        )
        self.normalizer = AudioNormalizer()
        self.classifier = InstrumentClassifier()
        self.segmenter = AudioSegmenter()
        self.cleaner = MIDICleaner.for_source(
            (backend_name or self.config.backend),
            mode=self.config.validation_mode,
        )
        self.piano_analyzer = PianoAudioAnalyzer()
        self.chord_detector = ChordDetector()
        self.role_separator = MelodyAccompanimentSeparator()
        self.hand_separator = build_hand_separator(self.config.hand_separator)
        self.voice_separator = VoiceSeparator()
        self.dynamics = DynamicsExtractor()
        self.articulation = ArticulationDetector()
        self.phrase_detector = PhraseDetector()
        self.meter_estimator = MeterEstimator()
        self.meter_arbitrator = MeterArbitrator(self.meter_estimator)
        self.notation = NotationWriter()
        self.beat_tracker = BeatTracker()
        if use_mir_layers is None:
            use_mir_layers = self.config.enable_mir_layers
        self.use_mir_layers = use_mir_layers
        self.last_debug: PipelineDebug | None = None
        self.last_structure: MusicalStructure | None = None
        self.last_meter_decision: MeterDecision | None = None
        self.last_raw_performance: RawPerformance | None = None
        self.last_performance_snapshot: PerformanceSnapshot | None = None
        # Observation-only stage snapshots for evaluation (not used by algorithms).
        self.last_raw_notes: list | None = None
        self.last_cleaned_notes: list | None = None
        self.last_validated_notes: list | None = None
        self.last_post_piano_notes: list | None = None
        self.last_quantized_events: list | None = None
        self.last_notation_notes: list | None = None
        self.last_clean_decisions: list | None = None
        self.last_gemini_applied: int = 0
        self._prefetched_tempo = None
        self.last_gemini_enabled: bool = False
        self.last_timing = None
        self.last_musical_time_map = None
        self._last_tracker_ms: float = 0.0
        self.last_export_ms: float = 0.0
        self.last_raw_identity: dict | None = None
        self.last_candidate_scores: list | None = None
        self.last_pickup: dict | None = None
        self.last_complexity_warnings: list[str] | None = None
        self.last_hand_summary: dict | None = None
        self.last_interpretation_choice: dict | None = None
        self.job: PipelineJob | None = None

    def transcribe(self, audio_path: str | Path, job_id: str) -> str:
        audio_path = Path(audio_path)
        if is_midi_path(audio_path):
            return self.transcribe_midi(audio_path, job_id)

        prepared = self.prepare_audio(audio_path, job_id)
        notes, prediction, segments = self._transcribe_with_cpu_overlap(
            prepared.backend, prepared.transcribe_path, prepared.normalized
        )
        return self.complete_audio(prepared, notes, prediction, segments)

    def prepare_audio(self, audio_path: str | Path, job_id: str) -> PreparedAudio:
        """Normalize once and bind the transcription backend. Does not beat-track or AMT."""
        audio_path = Path(audio_path)
        normalized = self.normalizer.normalize(audio_path)
        out_dir = audio_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)
        transcribe_path = self.normalizer.write_wav(
            normalized, out_dir / f"{job_id}_norm.wav"
        )
        backend = get_backend(self.backend_name)
        self.backend_name = backend.name
        self.config = load_pipeline_config(
            backend=backend.name,
            mode=self.mode,
            validation_mode=self._validation_override,
        )
        self.cleaner = MIDICleaner.for_source(
            backend.name, mode=self.config.validation_mode
        )
        print(
            f"[Pipeline] backend={backend.name} mode={self.mode} "
            f"validation={self.config.validation_mode.value} "
            f"quantize={self.config.quantization_mode.value} "
            f"gemini={self.config.enable_gemini} "
            f"piano_analysis={self.config.enable_piano_analysis} "
            f"(job={job_id})"
        )
        return PreparedAudio(
            audio_path=audio_path,
            job_id=job_id,
            normalized=normalized,
            transcribe_path=transcribe_path,
            backend=backend,
            out_dir=out_dir,
        )

    def complete_audio(
        self,
        prepared: PreparedAudio,
        notes,
        prediction,
        segments,
        *,
        interpret_notes=None,
    ) -> str:
        """Interpretation/export from an already-transcribed full-mix result.

        Does not call the AMT backend again. Reuses `_prefetched_tempo` when
        `_prefetch_cpu` already ran, so beat tracking stays a single pass.

        `notes` is the full-mix baseline (raw.mid / validated.mid). When
        federation supplies `interpret_notes`, those are scored instead; the
        mix set remains the reviewable baseline.
        """
        audio_path = prepared.audio_path
        job_id = prepared.job_id
        transcribe_path = prepared.transcribe_path
        normalized = prepared.normalized
        backend = prepared.backend
        out_dir = prepared.out_dir
        notes = [
            n.ensure_ids(i)
            for i, n in enumerate(notes)
        ]
        notes = [
            n
            if n.source_backend and n.source_backend != "unknown"
            else replace_source(n, backend.name)
            for n in notes
        ]
        mix_set = ImmutableNoteSet.from_notes(notes, source="full_mix")
        notes = mix_set.copy_notes()
        self.job = PipelineJob(
            job_id=job_id,
            notes=mix_set,
            mix_notes=mix_set,
            transcription=mix_set,
        )
        raw_count = len(notes)
        transcription = TranscriptionResult(
            notes=mix_set.copy_notes(),
            backend=backend.name,
            audio_path=str(transcribe_path),
        )
        self.last_raw_notes = mix_set.copy_notes()
        source_bytes = getattr(backend, "last_midi_bytes", None)
        provider_sha = getattr(backend, "last_provider_raw_sha256", None)
        self.last_performance_snapshot = getattr(backend, "last_performance", None)
        raw_path = job_raw_midi_path(audio_path, job_id)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        # Immutable raw.mid is the provider payload (or reconstructed Solo MIDI).
        # Write + independent SHA happen before cleaner, validation, or rewrite.
        if source_bytes is not None:
            if self.last_performance_snapshot is None:
                raise ValueError("MIDI backend returned bytes without source provenance")
            raw_path.write_bytes(source_bytes)
            if not provider_sha:
                from mir.raw_identity import sha256_hex

                provider_sha = sha256_hex(bytes(source_bytes))
        else:
            self.last_performance_snapshot = PerformanceSnapshot.from_notes(notes, backend.name)
            write_job_stage_midi(raw_path, notes, bpm=120.0, split_hands=False)
            provider_sha = None
        self.last_raw_identity = record_saved_raw(
            raw_path, provider_raw_sha256=provider_sha
        )
        if source_bytes is not None:
            self.last_performance_snapshot.verify_midi(source_bytes)
        self.last_performance_snapshot.write_json(out_dir / f"{job_id}.performance.json")

        if not notes:
            raise TranscriptionError("No notes detected")

        notes, clean_decisions = self.cleaner.clean_with_report(notes)
        validated_set = ImmutableNoteSet.from_notes(notes, source="full_mix_validated")
        self.job = replace(self.job, validated=validated_set)
        self.last_cleaned_notes = validated_set.copy_notes()
        self.last_validated_notes = validated_set.copy_notes()
        self.last_clean_decisions = list(clean_decisions)
        print(
            f"[MIDICleaner] mode={self.cleaner.mode.value} "
            f"notes {raw_count} → {len(notes)} (job={job_id})"
        )
        validated_path = job_validated_midi_path(audio_path, job_id)
        original_notes = self.last_performance_snapshot.to_notes()
        if source_bytes is not None and sorted(notes, key=lambda n: n.note_id) == sorted(original_notes, key=lambda n: n.note_id):
            validated_path.write_bytes(source_bytes)
        else:
            write_job_stage_midi(validated_path, notes, bpm=120.0, split_hands=False)

        if interpret_notes is not None:
            working = [
                n.ensure_ids(i)
                for i, n in enumerate(interpret_notes)
            ]
            working = [
                n
                if n.source_backend and n.source_backend != "unknown"
                else replace_source(n, backend.name)
                for n in working
            ]
            working_set = ImmutableNoteSet.from_notes(working, source="reconciled")
            notes = working_set.copy_notes()
        else:
            working_set = validated_set
            notes = validated_set.copy_notes()
        self.job = replace(self.job, notes=working_set)

        pedal_events: list[tuple[float, int]] = []
        pedal_obs: list[PedalObservation] = []
        run_piano = piano_analysis_enabled(backend.name) and _should_analyze_piano(
            prediction.instrument
        )
        if run_piano:
            # Metadata only: do not replace transcription velocities/onsets.
            piano = self.piano_analyzer.analyze(
                normalized, notes, mutate_velocity=False
            )
            pedal_events = [(p.time_sec, p.value) for p in piano.pedal_events]
            pedal_obs = [
                PedalObservation(
                    time_sec=p.time_sec, value=p.value, confidence=p.confidence
                )
                for p in piano.pedal_events
            ]
            print(
                f"[PianoAnalyzer] metadata only "
                f"(velocities preserved, suggestions={len(piano.velocity_suggestions or [])}) "
                f"pedal={len(pedal_events)} (job={job_id})"
            )
        self.last_post_piano_notes = list(notes)

        onsets = [n.start_time for n in notes]
        tempo_map, meter = self._build_tempo_map(normalized, audio_path, onsets)
        timing = self._resolve_timing(
            tempo_map,
            notes=notes,
            audio_duration_sec=normalized.duration_sec,
            backend_requested="existing_tracker",
        )
        performance_bpm = (
            timing.performance_median_bpm
            or timing.quality.median_bpm
            or tempo_map.bpm_at(0.0)
        )

        from mir.score_interpretation import (
            choose_candidate,
            evaluate_candidates,
            infer_pickup,
            scaled_time_map,
        )

        source_before = [
            (n.note_id, n.pitch, n.velocity, n.start_time, n.end_time) for n in notes
        ]
        candidates = evaluate_candidates(notes, timing.time_map)
        self.last_candidate_scores = [c.to_dict() for c in candidates]
        chosen = choose_candidate(candidates)
        if chosen is not None and abs(chosen.tempo_scale - 1.0) > 1e-9:
            new_map = scaled_time_map(timing.time_map, chosen.tempo_scale)
            timing = apply_score_time_map(
                timing,
                new_map,
                reason=f"score time retuned: tempo_scale={chosen.tempo_scale}",
                tempo_scale=chosen.tempo_scale,
            )
            self.last_timing = timing
            self.last_musical_time_map = timing.time_map
            print(
                f"[Interpretation] tempo_scale={chosen.tempo_scale} "
                f"meter_hint={chosen.meter} cost={chosen.total:.3f}"
            )
        assert [
            (n.note_id, n.pitch, n.velocity, n.start_time, n.end_time) for n in notes
        ] == source_before

        self.last_raw_performance = RawPerformance(
            notes=list(transcription.notes),
            pedal_events=pedal_obs,
            tempo_observations=[
                TempoObservation(
                    time_sec=0.0,
                    bpm=float(performance_bpm),
                    confidence=0.9,
                    source="beat_refine",
                )
            ],
            source_backend=backend.name,
            source_path=str(audio_path),
        )

        chords = self.chord_detector.detect(notes)
        role = self.role_separator.separate(notes)

        events = notes_to_events(
            notes,
            timing.time_map,
            role=role,
            instrument=prediction.instrument,
            source_backend=backend.name,
        )
        events = self._apply_mir_layers(events)

        meter_hyps = self.meter_estimator.estimate(events)
        decision = self._arbitrate_meter(events, file_meter=None, timing=timing)
        selected_meter = decision.hypothesis or meter_hyps[0]
        from mir.meter import meter_from_time_signature
        from mir.score_interpretation import APPLY_MARGIN

        scale = chosen.tempo_scale if chosen is not None else 1.0
        same_scale = [
            c
            for c in candidates
            if abs(c.tempo_scale - scale) < 1e-9
        ]
        best_at_scale = min(same_scale, key=lambda c: c.total) if same_scale else None
        arb_at_scale = next(
            (c for c in same_scale if c.meter == decision.meter),
            None,
        )
        if (
            best_at_scale is not None
            and arb_at_scale is not None
            and best_at_scale.meter != decision.meter
            and best_at_scale.total <= APPLY_MARGIN * max(arb_at_scale.total, 1e-6)
        ):
            selected_meter = meter_from_time_signature(
                best_at_scale.meter,
                confidence=0.7,
                source="interpretation_cost",
            )
            print(
                f"[Interpretation] meter={selected_meter.time_signature} "
                f"over {decision.meter} cost={best_at_scale.total:.3f}"
            )
        events = self._align_score_meter(events, notes, timing, selected_meter)
        self.last_timing = timing
        self.last_musical_time_map = timing.time_map
        first_beat = min((e.start_beat for e in events), default=0.0)
        down_beats = []
        result = getattr(self.beat_tracker, "last_beat_result", None)
        if result is not None:
            down_beats = [
                timing.time_map.seconds_to_beats(t)
                for t in (result.downbeat_times or [])
            ]
        self.last_pickup = infer_pickup(
            first_beat,
            selected_meter.measure_quarter_length,
            downbeat_beats=down_beats,
        )
        score_bpm = timing.quality.median_bpm
        if score_bpm is None:
            score_bpm = float(performance_bpm) * float(scale)
        self.last_interpretation_choice = {
            **(chosen.to_dict() if chosen is not None else {"tempo_scale": 1.0}),
            "tempo_scale": float(scale),
            "meter": selected_meter.time_signature,
            "performance_bpm": float(performance_bpm),
            "score_bpm": float(score_bpm),
        }
        for issue in score_time_consistency_issues(timing):
            timing.analysis.warnings.append(f"score-time consistency: {issue}")
        (out_dir / f"{job_id}.candidate_scores.json").write_text(
            json.dumps(
                {
                    "interpretation_choice": dict(self.last_interpretation_choice),
                    "candidates": list(self.last_candidate_scores or []),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        from mir.score_interpretation import summarize_hand_decisions

        self.last_hand_summary = summarize_hand_decisions(
            events,
            source=getattr(self.hand_separator, "last_source", "viterbi"),
        )
        structure = MusicalStructure(
            events=events,
            tempo_map=tempo_map,
            meter_hypotheses=meter_hyps,
            selected_meter=selected_meter,
            instrument=prediction.instrument,
            instrument_confidence=prediction.confidence,
            instrument_prediction=prediction,
            segments=list(segments),
            extra={
                "chords": [c.name for c in chords[:12]],
                "meter_decision": decision.to_dict(),
                "timing": timing.quality.to_dict(),
                "pickup": dict(self.last_pickup or {}),
                "interpretation_choice": dict(self.last_interpretation_choice),
                "meter_candidates": [
                    c for c in (self.last_candidate_scores or [])
                    if abs(float(c.get("tempo_scale", 1.0)) - float(scale)) < 1e-9
                ],
            },
        )
        self.last_structure = structure

        meta = build_score_meta(
            tempo_map,
            prediction.instrument,
            segments,
            display_bpm=self._display_bpm(score_bpm),
            instrument_confidence=prediction.confidence,
            time_sig_hint=selected_meter.time_signature,
        )
        meta.extra = {
            **(meta.extra or {}),
            "meter_source": "meter_decision",
            "meter_decision": decision.to_dict(),
            "timing": timing.quality.to_dict(),
            "printed_tempo": [
                {"beat": m.beat, "bpm": m.bpm, "mark": m.mark, "reason": m.reason}
                for m in timing.printed
            ],
            "interpretation_choice": dict(self.last_interpretation_choice),
        }
        meta.extra["playback_tempo"] = [
            {"beat": beat, "bpm": bpm}
            for beat, bpm in timing.time_map.interval_bpms()
        ]
        self._write_timing_artifact(out_dir, job_id, timing, decision)

        self._write_debug(
            job_id=job_id,
            out_dir=out_dir,
            backend_name=backend.name,
            raw_count=raw_count,
            notes=notes,
            clean_decisions=clean_decisions,
            prediction=prediction,
            bpm=float(score_bpm),
            selected_meter=selected_meter,
            events=events,
            role=role,
        )

        def _rebuild(next_notes, next_tempo, next_role):
            mapper = timing.time_map or next_tempo
            rebuilt = notes_to_events(
                next_notes,
                mapper,
                role=next_role,
                instrument=prediction.instrument,
                source_backend=backend.name,
            )
            return self._apply_mir_layers(rebuilt)

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
        performance_bpm = tempo_map.bpm_at(0.0)
        score_bpm = (
            self.last_timing.quality.median_bpm
            if self.last_timing is not None and self.last_timing.quality.median_bpm
            else performance_bpm
        )
        if self.last_interpretation_choice:
            performance_bpm = float(
                self.last_interpretation_choice.get("performance_bpm") or performance_bpm
            )
            score_bpm = float(
                self.last_interpretation_choice.get("score_bpm") or score_bpm
            )
        self.last_gemini_enabled = bool(self.config.enable_gemini)
        self.last_gemini_applied = int(enhanced.applied)

        print(
            f"[Understanding] instrument={prediction.instrument.value} "
            f"performance_tempo={performance_bpm:.1f} score_tempo={score_bpm:.1f} "
            f"meter={meta.time_sig_hint or '-'} "
            f"tempo_points={len(tempo_map.points)} "
            f"events={len(events)} mir_layers={self.use_mir_layers} "
            f"validation={self.config.validation_mode.value} "
            f"(job={job_id})"
        )

        # Rewrite validated MIDI with known tempo, but keep the post-cleaner
        # note list. Piano / Gemini must not silently replace this snapshot.
        write_job_stage_midi(
            job_validated_midi_path(audio_path, job_id),
            list(self.last_validated_notes or []),
            bpm=performance_bpm,
            pedal_events=pedal_events,
            split_hands=False,
            tempo_map=tempo_map,
        )

        export_started = time.perf_counter()
        # _align_score_meter already put events on the measured bar phase.
        # Passing performance-map downbeats here would rotate that grid twice.
        self.job = replace(
            self.job,
            time_map=timing.time_map if timing is not None else self.job.time_map,
            timing=timing if timing is not None else self.job.timing,
            structure=structure,
            meter_decision=decision,
            snapshot=self.last_performance_snapshot,
            extra={
                "interpretation_choice": dict(self.last_interpretation_choice or {}),
                "pickup": dict(self.last_pickup or {}),
            },
        )
        xml, notation_result = self.notation.write_musicxml_with_result(
            events,
            meta,
            job_id=job_id,
            audio_path=audio_path,
            quantize_divisors=QUANTIZE_DIVISORS,
            fallback_bpm=score_bpm,
            structure=structure,
            quantization_mode=QuantizationMode.PERFORMANCE,
        )
        self.last_quantized_events = list(notation_result.quantized_events)
        self.last_notation_notes = list(self.last_quantized_events)
        self.last_export_ms = (time.perf_counter() - export_started) * 1000.0
        self._publish_job(
            quantization=notation_result.quantization,
            notation=notation_result,
        )
        self._attach_notation_debug(job_id, out_dir)
        return xml

    def _prefetch_cpu(self, normalized):
        started = time.perf_counter()
        prediction = self.classifier.classify(normalized)
        segments = self.segmenter.segment(normalized)
        if _use_beat_tracker():
            tracked = self.beat_tracker.track_stable(normalized)
            self._last_tracker_ms = (time.perf_counter() - started) * 1000.0
            self._prefetched_tempo = (
                tracked,
                self.beat_tracker.last_time_signature,
            )
        print(
            f"[Pipeline] cpu_prep_seconds={time.perf_counter() - started:.2f}"
        )
        return prediction, segments

    def _transcribe_with_cpu_overlap(self, backend, transcribe_path, normalized):
        """Run remote/local transcription in parallel with CPU prep."""
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            notes_fut = pool.submit(backend.transcribe_notes, transcribe_path)
            cpu_fut = pool.submit(self._prefetch_cpu, normalized)
            notes = notes_fut.result()
            prediction, segments = cpu_fut.result()
        print(
            f"[Pipeline] overlap_wall_seconds={time.perf_counter() - started:.2f} "
            f"backend={backend.name}"
        )
        return notes, prediction, segments

    def transcribe_midi(self, midi_path: str | Path, job_id: str) -> str:
        """CMR entry for an uploaded MIDI file (no Basic Pitch)."""
        import shutil

        midi_path = Path(midi_path)
        ingested = ingest_midi(midi_path)
        self.last_performance_snapshot = ingested.performance
        notes = [n.ensure_ids(i) for i, n in enumerate(ingested.notes)]
        mix_set = ImmutableNoteSet.from_notes(notes, source="midi")
        notes = mix_set.copy_notes()
        validated_set = mix_set
        working_set = mix_set
        self.job = PipelineJob(
            job_id=job_id,
            notes=working_set,
            mix_notes=mix_set,
            transcription=mix_set,
            validated=validated_set,
        )
        tempo_map = ingested.tempo_map
        duration = max((n.end_time for n in notes), default=1.0)
        timing = resolve_from_tempo_map(
            tempo_map,
            duration_sec=duration,
            backend_requested="midi_file",
            backend_used="midi_file",
            fallback_used=False,
            failure_reason="",
            audio_duration_sec=duration,
        )
        # Integer beat samples are diagnostics; MIDI endpoints must use every
        # encoded tempo change, including changes inside a quarter note.
        timing.fallback_used = False
        timing.quality.fallback_used = False
        timing.failure_reason = ""
        timing.quality.failure_reason = ""
        self.last_timing = timing
        self.last_musical_time_map = timing.time_map
        self.job = replace(self.job, time_map=timing.time_map, timing=timing)
        bpm = timing.quality.median_bpm or tempo_map.bpm_at(0.0)
        # MIDI ingest has no transcription cleaner — raw == validated.
        self.last_raw_notes = list(notes)
        self.last_cleaned_notes = list(notes)
        self.last_validated_notes = list(notes)
        self.last_post_piano_notes = list(notes)
        self.last_clean_decisions = []
        self.last_gemini_enabled = False
        self.last_gemini_applied = 0
        self.config = load_pipeline_config(
            backend="midi",
            mode=self.mode,
            validation_mode=self._validation_override,
        )
        if self.config.quantization_mode.value == "performance" and len(ingested.performance.meter_changes) > 1:
            raise ValueError("Changing meter is not yet supported by the solo score planner")

        out_dir = midi_path.parent / f"bp_{job_id}"
        out_dir.mkdir(exist_ok=True)
        self.last_performance_snapshot.write_json(out_dir / f"{job_id}.performance.json")
        raw_path = job_raw_midi_path(midi_path, job_id)
        if midi_path.resolve() != raw_path.resolve():
            shutil.copy2(midi_path, raw_path)
        validated_path = job_validated_midi_path(midi_path, job_id)
        if midi_path.resolve() != validated_path.resolve():
            shutil.copy2(midi_path, validated_path)

        role = self.role_separator.separate(notes)
        kinds = {n.instrument for n in notes}
        midi_instrument = next(iter(kinds)) if len(kinds) == 1 else InstrumentKind.UNKNOWN
        events = notes_to_events(
            notes,
            tempo_map,
            role=role,
            instrument=midi_instrument,
            source_backend="midi",
        )
        events = self._apply_mir_layers(events)

        meter_hyps = self.meter_estimator.estimate(events)
        decision = self._arbitrate_meter(
            events, file_meter=ingested.time_sig_hint, timing=timing
        )
        selected_meter = decision.hypothesis or meter_hyps[0]
        structure = MusicalStructure(
            events=events,
            tempo_map=tempo_map,
            meter_hypotheses=meter_hyps,
            selected_meter=selected_meter,
            instrument=midi_instrument,
            instrument_confidence=0.9,
            extra={
                "source": "midi",
                "meter_decision": decision.to_dict(),
                "file_meter": ingested.time_sig_hint,
                "timing": timing.quality.to_dict(),
            },
        )
        self.last_structure = structure

        meta = build_score_meta(
            tempo_map,
            midi_instrument,
            [],
            display_bpm=self._display_bpm(bpm),
            instrument_confidence=0.9,
            time_sig_hint=decision.meter,
        )
        meta.extra = {
            **(meta.extra or {}),
            "preserve_midi_tempo": True,
            "meter_source": "meter_decision",
            "meter_decision": decision.to_dict(),
            "file_meter": ingested.time_sig_hint,
            "timing": timing.quality.to_dict(),
            "printed_tempo": [
                {"beat": m.beat, "bpm": m.bpm, "mark": m.mark, "reason": m.reason}
                for m in timing.printed
            ],
        }
        self._write_timing_artifact(out_dir, job_id, timing, decision)
        from intelligence.layer import maybe_enhance
        from mir.types import InstrumentPrediction

        midi_pred = InstrumentPrediction(instrument=midi_instrument, confidence=0.9)

        def _rebuild(next_notes, next_tempo, next_role):
            mapper = timing.time_map or next_tempo
            rebuilt = notes_to_events(
                next_notes,
                mapper,
                role=next_role,
                instrument=midi_instrument,
                source_backend="midi",
            )
            return self._apply_mir_layers(rebuilt)

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
        xml, notation_result = self.notation.write_musicxml_with_result(
            events,
            meta,
            job_id=job_id,
            audio_path=midi_path,
            quantize_divisors=QUANTIZE_DIVISORS,
            fallback_bpm=bpm,
            structure=structure,
            quantization_mode=QuantizationMode.PERFORMANCE,
        )
        self.last_quantized_events = list(notation_result.quantized_events)
        self.last_notation_notes = list(self.last_quantized_events)
        self.last_gemini_enabled = bool(self.config.enable_gemini)
        self.last_gemini_applied = int(enhanced.applied)
        self.job = replace(
            self.job,
            structure=structure,
            meter_decision=decision,
            snapshot=self.last_performance_snapshot,
        )
        self._publish_job(
            quantization=notation_result.quantization,
            notation=notation_result,
        )
        self._attach_notation_debug(job_id, out_dir)
        return xml

    def _attach_notation_debug(self, job_id: str, out_dir: Path) -> None:
        payload = self.notation.notation_debug_payload()
        if self.last_debug is None:
            self.last_debug = PipelineDebug(job_id=job_id, pipeline="understanding")
        self.last_debug.fallback_used = bool(payload.get("fallback_used"))
        self.last_debug.quantization_decisions = list(
            payload.get("quantization_decisions") or []
        )
        extra = dict(self.last_debug.extra)
        extra["notation_path"] = payload.get("notation_path")
        extra["notation_fallback_error"] = payload.get("notation_fallback_error")
        extra["notation_time_signature"] = payload.get("time_signature")
        extra["notation_measure_count"] = payload.get("measure_count")
        extra["notation_plan_success"] = payload.get("notation_plan_success")
        extra["notation_plan_failure"] = payload.get("notation_plan_failure")
        extra["legacy_fallback_used"] = payload.get("legacy_fallback_used")
        extra["music21_conversion_failure"] = payload.get("music21_conversion_failure")
        extra["musicxml_export_failure"] = payload.get("musicxml_export_failure")
        extra["export_integrity"] = payload.get("export_integrity") or {}
        extra["notation_mode"] = payload.get("notation_mode")
        extra["fit_trim_count"] = payload.get("fit_trim_count")
        extra["invariant_issue_count"] = len(payload.get("invariant_issues") or [])
        extra["quantization_summary"] = payload.get("quantization_summary") or {}
        extra["validation_mode"] = self.config.validation_mode.value
        extra["quantization_mode"] = self.config.quantization_mode.value
        extra["gemini_enabled"] = bool(self.last_gemini_enabled)
        extra["gemini_applied"] = int(self.last_gemini_applied)
        extra["raw_note_count"] = (
            len(self.last_raw_notes) if self.last_raw_notes is not None else None
        )
        extra["validated_note_count"] = (
            len(self.last_validated_notes)
            if self.last_validated_notes is not None
            else None
        )
        extra["notation_note_count"] = len(self.last_quantized_events or [])
        extra["quantized_events_changed"] = (payload.get("quantization_summary") or {}).get(
            "events_changed"
        )
        extra["backend"] = self.last_debug.source_backend
        extra["pickup"] = dict(self.last_pickup or {})
        extra["interpretation_choice"] = dict(self.last_interpretation_choice or {})
        extra["candidate_scores"] = list(self.last_candidate_scores or [])
        extra["hand_decisions"] = dict(self.last_hand_summary or {})
        extra["pipeline_config_extra"] = dict(self.config.extra or {})
        if self.last_meter_decision is not None:
            extra["meter_decision"] = self.last_meter_decision.to_dict()
        if self.last_timing is not None:
            extra["timing"] = self.last_timing.quality.to_dict()
        from mir.score_metrics import metrics_from_plan, warnings_from_metrics

        plan = getattr(self.notation, "last_plan", None)
        source_notes = self.last_raw_notes or self.last_validated_notes or []
        metrics = metrics_from_plan(
            plan,
            source_notes=source_notes,
            quantized=self.last_quantized_events,
        )
        extra["score_metrics"] = metrics
        self.last_complexity_warnings = warnings_from_metrics(metrics)
        extra["notation_complexity_warning"] = list(self.last_complexity_warnings or [])
        if self.job is not None:
            extra["job"] = self.job.to_dict()
            extra["notes_source"] = self.job.notes.source
            extra["mix_note_count"] = len(self.job.mix_notes)
        self.last_debug.extra = extra
        out_dir = Path(out_dir)
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{job_id}.score_metrics.json").write_text(
            json.dumps(metrics, indent=2) + "\n",
            encoding="utf-8",
        )
        if payload.get("fallback_used"):
            print(
                "[Notation] debug: fallback to legacy build_score "
                f"({payload.get('notation_fallback_error')})"
            )
        self.last_debug.write_json(out_dir / f"{job_id}.debug.json")

    def _publish_job(
        self,
        *,
        quantization,
        notation,
    ) -> PipelineJob:
        """Attach returned stage results to the job created before processing.

        `last_*` fields remain diagnostics derived from this object. They are
        not read to coordinate stages.
        """
        if self.job is None:
            raise RuntimeError("PipelineJob must be created before processing")
        job = replace(
            self.job,
            quantization=quantization.copy() if quantization is not None else None,
            notation=notation.copy() if notation is not None else None,
        )
        self.job = job
        if job.structure is not None:
            self.last_structure = job.structure
        if job.meter_decision is not None:
            self.last_meter_decision = job.meter_decision
        if job.timing is not None:
            self.last_timing = job.timing
            self.last_musical_time_map = job.time_map
        if job.notation is not None:
            self.last_quantized_events = list(job.notation.quantized_events)
            self.last_notation_notes = list(job.notation.quantized_events)
        return job

    def _arbitrate_meter(
        self,
        events: list,
        *,
        file_meter: str | None = None,
        timing=None,
    ) -> MeterDecision:
        """Canonical meter decision from estimator + beat grouping + accents."""
        evidence = None
        result = getattr(self.beat_tracker, "last_beat_result", None)
        timing = timing if timing is not None else self.last_timing
        if result is not None:
            evidence = BeatGroupingEvidence(
                source=self.beat_tracker.last_source or "madmom",
                beats_per_bar=int(result.beats_per_bar),
                grouping_meter=result.grouping_meter or result.time_signature,
                beat_times=list(result.beat_times),
                downbeat_times=list(result.downbeat_times),
                grouping_beats_per_bar=int(
                    result.grouping_beats_per_bar or result.beats_per_bar
                ),
                bpm=float(result.bpm),
                extra={
                    "search": result.grouping_search,
                    "grouping_positions": list(result.grouping_positions),
                },
            )
        elif (
            timing is not None
            and timing.backend_used not in ("midi_file",)
            and not str(timing.backend_used).startswith("constant_bpm")
            and not str(timing.backend_used).startswith("tempo_map")
        ):
            analysis = timing.analysis
            evidence = BeatGroupingEvidence(
                source=analysis.model,
                beat_times=list(analysis.beat_times),
                downbeat_times=list(analysis.downbeat_times),
                bpm=timing.quality.median_bpm,
            )
        decision = self.meter_arbitrator.decide(
            events,
            beat_evidence=evidence,
            file_meter=file_meter,
        )
        self.last_meter_decision = decision
        print(
            f"[Meter] {decision.meter} conf={decision.confidence:.2f} "
            f"reason={decision.reason} override={decision.was_hint_overridden}"
        )
        return decision

    def _display_bpm(self, bpm: float) -> int:
        if not quantization_snaps_display_tempo(self.config.quantization_mode):
            return max(1, int(round(float(bpm))))
        return snap_to_standard_tempo(bpm)

    def _tempo_hypotheses(self, score_bpm: float) -> list[dict]:
        choice = dict(self.last_interpretation_choice or {})
        performance_bpm = choice.get("performance_bpm")
        rows = []
        if performance_bpm is not None:
            rows.append({"bpm": float(performance_bpm), "source": "performance"})
        rows.append({"bpm": float(score_bpm), "source": "score"})
        return rows

    def _apply_mir_layers(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        if not self.use_mir_layers:
            return events
        if self.config.quantization_mode.value == "performance":
            from mir.performance_score import assign_pipeline_layout
            from mir.score_profile import score_profile

            return assign_pipeline_layout(
                events,
                score_profile(events),
                self.hand_separator,
                self.voice_separator,
            )
        events = self.hand_separator.separate(events)
        events = self.voice_separator.separate(events)
        events = self.dynamics.extract(events)
        events = self.articulation.detect(events)
        return self.phrase_detector.assign(events)

    def _write_debug(
        self,
        *,
        job_id: str,
        out_dir: Path,
        backend_name: str,
        raw_count: int,
        notes: list[NoteEvent],
        clean_decisions,
        prediction,
        bpm: float,
        selected_meter,
        events: list[MusicalEvent],
        role,
    ) -> None:
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
            source_backend=backend_name,
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
            tempo_hypotheses=self._tempo_hypotheses(bpm),
            selected_tempo_bpm=bpm,
            selected_meter=selected_meter.time_signature,
            meter_confidence=(
                self.last_meter_decision.confidence
                if self.last_meter_decision is not None
                else selected_meter.confidence
            ),
            hand_assignments=hand_counts,
            voice_assignments=voice_counts,
            extra={
                "meter_decision": (
                    self.last_meter_decision.to_dict()
                    if self.last_meter_decision is not None
                    else None
                ),
                "role_confidence": role.confidence,
                "validation_mode": self.config.validation_mode.value,
                "quantization_mode": self.config.quantization_mode.value,
                "hand_separator": self.config.hand_separator.value,
                "hand_separator_source": getattr(
                    self.hand_separator, "last_source", "viterbi"
                ),
                "gemini_enabled": bool(self.config.enable_gemini),
                "gemini_applied": 0,
                "backend": backend_name,
                "timing": (
                    self.last_timing.quality.to_dict() if self.last_timing is not None else None
                ),
                "pickup": dict(self.last_pickup or {}),
                "interpretation_choice": dict(self.last_interpretation_choice or {}),
                "candidate_scores": list(self.last_candidate_scores or []),
                "hand_decisions": dict(self.last_hand_summary or {}),
                "notation_complexity_warning": list(self.last_complexity_warnings or []),
                "pipeline_config_extra": dict(self.config.extra or {}),
                **(
                    {
                        "hand_decision_details": [
                            {
                                "note_id": d.note_id,
                                "pitch": d.pitch,
                                "start_beat": d.start_beat,
                                "selected": d.selected,
                                "confidence": d.confidence,
                                "competing_hand": d.competing_hand,
                                "competing_cost_delta": d.competing_cost_delta,
                                "factors": d.factors,
                            }
                            for d in self.hand_separator.last_decisions
                        ]
                    }
                    if _env_enabled("TRANSCRIPTION_DEBUG_HANDS", default=False)
                    else {}
                ),
            },
        )
        self.last_debug = debug
        debug.write_json(out_dir / f"{job_id}.debug.json")

    def _resolve_timing(
        self,
        tempo_map: TempoMap,
        *,
        notes: list[NoteEvent],
        audio_duration_sec: float | None,
        backend_requested: str,
    ):
        duration = max(
            float(audio_duration_sec or 0.0),
            max((n.end_time for n in notes), default=1.0),
            1.0,
        )
        timing = resolve_from_existing_tracker(
            self.beat_tracker,
            tempo_map,
            duration_sec=duration,
            audio_duration_sec=audio_duration_sec,
            tracker_wall_ms=self._last_tracker_ms,
        )
        timing.backend_requested = backend_requested
        timing.quality.backend_requested = backend_requested
        if notes:
            timing = align_score_origin(
                timing, min(n.start_time for n in notes),
            )
        self.last_timing = timing
        self.last_musical_time_map = timing.time_map
        print(
            f"[Timing] backend={timing.backend_used} beats={timing.quality.beat_count} "
            f"median_bpm={timing.quality.median_bpm} fallback={timing.fallback_used} "
            f"ms={timing.duration_ms:.1f}"
        )
        return timing

    def _align_score_meter(self, events, notes, timing, selected_meter):
        """Apply measured bar phase only when its units match the chosen meter."""
        from mir.types import copy_event

        result = getattr(self.beat_tracker, "last_beat_result", None)
        beats_per_bar = getattr(result, "beats_per_bar", None)
        if not notes or beats_per_bar != selected_meter.measure_quarter_length:
            return events
        old_map = timing.time_map
        align_score_origin(
            timing,
            min(n.start_time for n in notes),
            downbeat_times=getattr(result, "downbeat_times", ()) or (),
            beats_per_bar=beats_per_bar,
        )
        self.last_timing = timing
        self.last_musical_time_map = timing.time_map
        shift = timing.time_map.seconds_to_beats(old_map.beat_times[0])
        return [copy_event(ev, start_beat=ev.start_beat + shift) for ev in events]

    def _write_timing_artifact(self, out_dir: Path, job_id: str, timing, decision) -> None:
        candidates = None
        if decision is not None:
            candidates = list(decision.candidate_scores or [])
        timing.write_json(out_dir / f"{job_id}.tempo.json", meter_candidates=candidates)

    def _build_tempo_map(
        self, normalized, audio_path, onsets: list[float]
    ) -> tuple[TempoMap, str | None]:
        if _use_beat_tracker():
            if self._prefetched_tempo is not None:
                tracked, meter = self._prefetched_tempo
                self._prefetched_tempo = None
            else:
                started = time.perf_counter()
                tracked = self.beat_tracker.track_stable(normalized)
                meter = self.beat_tracker.last_time_signature
                self._last_tracker_ms = (time.perf_counter() - started) * 1000.0
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
                note_id=e.note_id,
                source_backend=e.source_backend,
                hand=e.hand,
            )
            for e in events
        ]


def replace_source(note: NoteEvent, backend: str) -> NoteEvent:
    from dataclasses import replace as dc_replace

    return dc_replace(note, source_backend=backend)
