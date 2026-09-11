"""Stage orchestrator. Existing UnderstandingPipeline remains the score engine."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.artifacts import ArtifactKind, ArtifactManifest, ref_for_file
from engine.clock import StageTimer
from engine.flags import (
    ensemble_render_enabled,
    fusion_enabled,
    fusion_ghost_confidence,
    fusion_stem_only_min_confidence,
    pipeline_mode,
    runtime_identification,
    separation_enabled,
    stem_transcription_enabled,
    write_manifest_enabled,
)
from engine.ir import InterpretedNote, InterpretedPerformance
from engine.provenance import live_provenance_fields
from engine.stages import StageName, StageResult
from mir.midi_ingest import ingest_midi, is_midi_path
from mir.pipeline import UnderstandingPipeline
from mir.raw_midi import (
    job_fused_midi_path,
    job_raw_midi_path,
    job_score_midi_path,
    job_validated_midi_path,
    write_notes_to_midi,
)
from modes import is_polyphonic
from separation.base import SeparationResult
from separation.service import get_separator
from timing.tempo_map import MusicalTimeMap
from transcription_fed.reconcile import ReconciliationResult, reconcile_transcriptions
from transcription_fed.stems import stem_is_pitched, transcribe_stem


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _unwrap_pipeline(engine):
    return getattr(engine, "primary", engine)


@dataclass
class OrchestratorResult:
    musicxml: str
    stages: list[StageResult]
    manifest: ArtifactManifest
    interpreted: InterpretedPerformance | None = None
    warnings: list[str] = field(default_factory=list)
    time_map: MusicalTimeMap | None = None
    fusion: ReconciliationResult | None = None

    def stage(self, name: StageName) -> StageResult | None:
        for row in self.stages:
            if row.name == name:
                return row
        return None


class PipelineOrchestrator:
    """Typed stages around the current production engine.

    Live audio jobs own preprocess / AMT / optional separation. Score export
    still goes through UnderstandingPipeline. Ensemble rendering stays off.
    """

    def run(
        self,
        source: str | Path,
        job_id: str,
        *,
        meter: str | None = None,
        mode: str | None = None,
        filename: str | None = None,
    ) -> OrchestratorResult:
        source = Path(source)
        label = filename or str(source)
        if is_midi_path(label) or is_midi_path(source):
            return self.run_midi(source, job_id, meter=meter)
        return self.run_audio(source, job_id, mode=mode)

    def run_audio(
        self, audio_path: str | Path, job_id: str, *, mode: str | None = None
    ) -> OrchestratorResult:
        from transcription import get_engine

        audio_path = Path(audio_path)
        stages: list[StageResult] = []
        warnings: list[str] = []
        ingest = StageTimer(StageName.INGEST)
        stages.append(
            ingest.result(
                ok=True,
                model="audio_file",
                extra={"path": str(audio_path), "pipeline_mode": pipeline_mode()},
            )
        )

        engine = get_engine(mode=mode, filename=str(audio_path))
        pipeline = _unwrap_pipeline(engine)
        if not isinstance(pipeline, UnderstandingPipeline):
            xml = engine.transcribe(audio_path, job_id)
            return self._finish(audio_path, job_id, xml, pipeline, stages, warnings)

        prep = StageTimer(StageName.PREPROCESS)
        prepared = pipeline.prepare_audio(audio_path, job_id)
        stages.append(
            prep.result(
                ok=True,
                model="audio_normalizer",
                artifacts=[str(prepared.transcribe_path)],
            )
        )

        poly = False
        try:
            poly = is_polyphonic(mode or pipeline.mode)
        except ValueError:
            poly = False
        # First production cutover: polyphonic jobs still skip federation unless
        # separation is explicitly enabled. DisabledSeparator is not scheduled.
        want_sep = poly and separation_enabled()
        backend = prepared.backend
        amt_timer = StageTimer(StageName.TRANSCRIBE_GLOBAL)
        cpu_timer = StageTimer(StageName.ANALYZE_AUDIO)
        sep_timer = StageTimer(StageName.SEPARATE)

        def run_amt():
            return backend.transcribe_notes(prepared.transcribe_path)

        def run_cpu():
            return pipeline._prefetch_cpu(prepared.normalized)

        def run_sep() -> SeparationResult:
            return get_separator().separate(
                str(prepared.transcribe_path),
                job_id=job_id,
                output_dir=str(prepared.out_dir),
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            amt_fut = pool.submit(run_amt)
            cpu_fut = pool.submit(run_cpu)
            sep_fut = pool.submit(run_sep) if want_sep else None
            try:
                notes = amt_fut.result()
            except Exception as exc:
                stages.append(
                    amt_timer.result(
                        ok=False,
                        model=getattr(backend, "name", ""),
                        requested_backend=getattr(backend, "name", ""),
                        actual_backend="",
                        error=str(exc),
                    )
                )
                if poly:
                    stages.append(
                        StageResult(
                            StageName.TRANSCRIBE_STEMS,
                            ok=True,
                            skipped=True,
                            skip_reason=(
                                "full-mix transcription failed; stem Basic Pitch "
                                "is not a silent substitute in Polyphonic mode"
                            ),
                            duration_ms=0.0,
                        )
                    )
                raise
            prediction, segments = cpu_fut.result()
            stages.append(
                cpu_timer.result(
                    ok=True,
                    model="existing_tracker",
                    extra={
                        "tracker_ms": pipeline._last_tracker_ms,
                        "beat_count": len(getattr(pipeline.beat_tracker, "last_beat_times", []) or []),
                    },
                )
            )
            mt3_meta = dict(getattr(backend, "last_timing", None) or {})
            stages.append(
                amt_timer.result(
                    ok=True,
                    model=getattr(backend, "name", ""),
                    backend=getattr(backend, "name", ""),
                    requested_backend=getattr(backend, "name", ""),
                    actual_backend=getattr(backend, "name", ""),
                    extra={
                        "notes": len(notes),
                        "queue_ms": mt3_meta.get("queue_ms"),
                        "execution_ms": mt3_meta.get("execution_ms"),
                        "wall_ms": mt3_meta.get("wall_ms"),
                        "warmup": False,
                    },
                )
            )

            interpret_timer = StageTimer(StageName.INTERPRET_SCORE)
            export_ms = 0.0

            def run_interpret():
                return pipeline.complete_audio(prepared, notes, prediction, segments)

            with ThreadPoolExecutor(max_workers=4) as later:
                interpret_fut = later.submit(run_interpret)
                if want_sep:
                    separation = sep_fut.result() if sep_fut is not None else _skipped_sep()
                else:
                    skip_reason = (
                        "NEXTGEN_SEPARATION_ENABLED is off"
                        if poly
                        else "solo/SOLO_INSTRUMENT routing skips GPU separation"
                    )
                    separation = SeparationResult(
                        stems=[],
                        model="skipped",
                        skipped=True,
                        skip_reason=skip_reason,
                        requested_backend="separator",
                        actual_backend="",
                    )
                stages.append(_separation_stage(sep_timer, separation, want_sep))
                if separation.error:
                    warnings.append(separation.error)
                elif separation.skipped:
                    warnings.append(separation.skip_reason)

                stem_rows = self._transcribe_stems(
                    later,
                    separation,
                    job_id=job_id,
                    source=audio_path,
                )
                xml = interpret_fut.result()
                export_ms = float(getattr(pipeline, "last_export_ms", 0.0) or 0.0)

            stages.append(
                interpret_timer.result(
                    ok=True,
                    model=str(pipeline.config.quantization_mode.value),
                    extra={
                        "bundled_with": "existing_understanding_pipeline",
                        "export_ms": export_ms,
                        "ensemble_render": ensemble_render_enabled(),
                    },
                )
            )
            stages.append(_stem_stage(stem_rows))

        fusion = self._fuse(
            audio_path,
            job_id,
            pipeline,
            notes,
            stem_rows,
            stages,
            warnings,
        )
        snapshot = pipeline.last_performance_snapshot
        identity = dict(getattr(pipeline, "last_raw_identity", None) or {})
        stages.append(
            StageResult(
                StageName.BUILD_PERFORMANCE,
                ok=True,
                duration_ms=0.0,
                model="PerformanceSnapshot",
                extra={
                    "midi_sha256": getattr(snapshot, "midi_sha256", None),
                    "provider_raw_sha256": identity.get("provider_raw_sha256"),
                    "saved_raw_sha256": identity.get("saved_raw_sha256"),
                    "raw_identity_match": identity.get("raw_identity_match"),
                },
            )
        )
        timing = pipeline.last_timing
        time_map = pipeline.last_musical_time_map
        stages.append(
            StageResult(
                StageName.ANALYZE_TIME,
                ok=True,
                duration_ms=float(getattr(pipeline, "_last_tracker_ms", 0.0) or 0.0),
                model=getattr(timing, "backend_used", "") if timing is not None else "",
                requested_backend="existing_tracker",
                actual_backend=getattr(timing, "backend_used", "") if timing is not None else "",
                fallback_used=bool(getattr(timing, "fallback_used", False)),
                extra={
                    "beats": len(getattr(time_map, "beat_times", []) or []),
                    "reused": True,
                },
            )
        )
        interpreted = None
        if time_map is not None:
            interpreted = self._interpreted(pipeline, time_map)
        result = self._finish(
            audio_path,
            job_id,
            xml,
            pipeline,
            stages,
            warnings,
            time_map=time_map,
            interpreted=interpreted,
            fusion=fusion,
        )
        return result

    def shadow_existing(
        self,
        source: str | Path,
        job_id: str,
        *,
        engine,
        musicxml: str,
    ) -> OrchestratorResult:
        """Record analysis around an already-finished production transcription.

        Must not send another MT3 request, beat-track, run Basic Pitch on the
        mix, separate, or rewrite MusicXML / score MIDI / raw MIDI.
        """
        source = Path(source)
        pipeline = _unwrap_pipeline(engine)
        warnings = ["shadow mode: production artifacts remain authoritative"]
        reused_backend = getattr(getattr(pipeline, "config", None), "backend", "") or getattr(
            pipeline, "backend_name", ""
        )
        stages = [
            StageResult(
                StageName.INGEST,
                ok=True,
                duration_ms=0.0,
                extra={"pipeline_mode": "shadow"},
            ),
            StageResult(
                StageName.PREPROCESS,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="shadow reuses the production preprocess",
            ),
            StageResult(
                StageName.ANALYZE_AUDIO,
                ok=True,
                duration_ms=float(getattr(pipeline, "_last_tracker_ms", 0.0) or 0.0),
                skipped=True,
                skip_reason="shadow must not beat-track a second time",
                extra={"reused_tracker_ms": getattr(pipeline, "_last_tracker_ms", 0.0)},
            ),
            StageResult(
                StageName.SEPARATE,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="shadow must not run GPU separation",
            ),
            StageResult(
                StageName.TRANSCRIBE_GLOBAL,
                ok=True,
                duration_ms=0.0,
                model=str(reused_backend),
                backend=str(reused_backend),
                extra={"reused": True, "shadow": True},
            ),
            StageResult(
                StageName.TRANSCRIBE_STEMS,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="shadow must not run extra Basic Pitch",
            ),
            StageResult(
                StageName.RECONCILE,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="shadow fusion diagnostics skipped; mix transcription unchanged",
            ),
            StageResult(
                StageName.BUILD_PERFORMANCE,
                ok=True,
                duration_ms=0.0,
                model="PerformanceSnapshot",
                extra={
                    "midi_sha256": getattr(pipeline.last_performance_snapshot, "midi_sha256", None)
                    if getattr(pipeline, "last_performance_snapshot", None) is not None
                    else None
                },
            ),
            StageResult(
                StageName.ANALYZE_TIME,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="shadow reuses MusicalTimeMap from the production pass",
                extra={
                    "beats": len(getattr(pipeline.last_musical_time_map, "beat_times", []) or [])
                    if getattr(pipeline, "last_musical_time_map", None) is not None
                    else 0
                },
            ),
            StageResult(
                StageName.INTERPRET_SCORE,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="shadow does not rewrite MusicXML or score MIDI",
            ),
        ]
        interpreted = None
        time_map = getattr(pipeline, "last_musical_time_map", None)
        if time_map is not None and getattr(pipeline, "last_quantized_events", None):
            interpreted = self._interpreted(pipeline, time_map)
        return self._finish(
            source,
            job_id,
            musicxml,
            pipeline,
            stages,
            warnings,
            time_map=time_map,
            interpreted=interpreted,
            rewrite_tempo=False,
        )

    def run_midi(self, midi_path: str | Path, job_id: str, *, meter: str | None = None) -> OrchestratorResult:
        midi_path = Path(midi_path)
        stages: list[StageResult] = []
        warnings: list[str] = []

        t0 = time.perf_counter()
        ingested = ingest_midi(midi_path)
        stages.append(
            StageResult(
                StageName.INGEST,
                ok=True,
                duration_ms=_ms(t0),
                model="midi_ingest",
                extra={"notes": len(ingested.notes), "midi_sha256": ingested.performance.midi_sha256},
            )
        )
        stages.append(
            StageResult(
                StageName.PREPROCESS,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="MIDI ingest has no audio preprocess",
            )
        )
        stages.append(
            StageResult(
                StageName.ANALYZE_AUDIO,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="no audio; tempo/meter taken from the MIDI file",
            )
        )
        t1 = time.perf_counter()
        stages.append(
            StageResult(
                StageName.SEPARATE,
                ok=True,
                duration_ms=_ms(t1),
                model="skipped",
                skipped=True,
                skip_reason="MIDI job does not run source separation",
            )
        )
        stages.append(
            StageResult(
                StageName.TRANSCRIBE_GLOBAL,
                ok=True,
                duration_ms=0.0,
                model="midi_ingest",
                extra={"notes": len(ingested.notes)},
            )
        )
        stages.append(
            StageResult(
                StageName.TRANSCRIBE_STEMS,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="no stems; full-mix MIDI is the only stream",
            )
        )
        t2 = time.perf_counter()
        fused = reconcile_transcriptions(ingested.notes, [], global_backend="midi")
        stages.append(
            StageResult(
                StageName.RECONCILE,
                ok=True,
                duration_ms=_ms(t2),
                model="identity",
                extra={"canonical_notes": len(fused.notes), "dropped_ghosts": 0},
            )
        )
        stages.append(
            StageResult(
                StageName.BUILD_PERFORMANCE,
                ok=True,
                duration_ms=0.0,
                model="PerformanceSnapshot",
                extra={"midi_sha256": ingested.performance.midi_sha256},
            )
        )
        duration = max((n.end_time for n in ingested.notes), default=1.0)
        time_map = MusicalTimeMap.from_tempo_map(ingested.tempo_map, duration_sec=duration)
        stages.append(
            StageResult(
                StageName.ANALYZE_TIME,
                ok=True,
                duration_ms=0.0,
                model=time_map.source,
                extra={"beats": len(time_map.beat_times)},
            )
        )
        t3 = time.perf_counter()
        pipeline = UnderstandingPipeline()
        xml = pipeline.transcribe_midi(midi_path, job_id)
        stages.append(
            StageResult(
                StageName.INTERPRET_SCORE,
                ok=True,
                duration_ms=_ms(t3),
                model=str(pipeline.config.quantization_mode.value),
                extra={"quantization_mode": pipeline.config.quantization_mode.value},
            )
        )
        interpreted = self._interpreted(pipeline, time_map)
        result = self._finish(
            midi_path,
            job_id,
            xml,
            pipeline,
            stages,
            warnings,
            time_map=time_map,
            interpreted=interpreted,
            fusion=fused,
        )
        return result

    def _transcribe_stems(self, pool, separation: SeparationResult, *, job_id: str, source: Path):
        if not stem_transcription_enabled():
            return []
        if separation.skipped or separation.error or not separation.stems:
            return []
        eligible = [stem for stem in separation.stems if stem_is_pitched(stem.stem_id)]
        futs = [
            pool.submit(
                transcribe_stem,
                stem.path,
                stem_id=stem.stem_id,
                job_id=job_id,
                source_path=source,
            )
            for stem in eligible
        ]
        return [fut.result() for fut in futs]

    def _fuse(
        self,
        audio_path: Path,
        job_id: str,
        pipeline: UnderstandingPipeline,
        mix_notes,
        stem_rows,
        stages: list[StageResult],
        warnings: list[str],
    ) -> ReconciliationResult | None:
        timer = StageTimer(StageName.RECONCILE)
        if not fusion_enabled():
            stages.append(
                timer.result(
                    ok=True,
                    skipped=True,
                    skip_reason="NEXTGEN_FUSION_ENABLED is off",
                )
            )
            return None
        specialist = []
        for row in stem_rows:
            if row.error:
                warnings.append(f"stem {row.stem_id} transcription failed: {row.error}")
                continue
            specialist.extend(row.notes)
        mix_backend = getattr(getattr(pipeline, "config", None), "backend", "mt3") or "mt3"
        fused = reconcile_transcriptions(
            list(mix_notes),
            specialist,
            global_backend=mix_backend,
            specialist_backend="basic_pitch",
            keep_global_timing=True,
            ghost_confidence=fusion_ghost_confidence(),
            stem_only_min_confidence=fusion_stem_only_min_confidence(),
        )
        out_dir = audio_path.parent / f"bp_{job_id}"
        fused_midi = job_fused_midi_path(audio_path, job_id)
        write_notes_to_midi(fused.notes, fused_midi, split_hands=False)
        fusion_path = out_dir / f"{job_id}.fusion.json"
        fused_json = out_dir / f"{job_id}.fused.json"
        payload = _fusion_payload(fused)
        fusion_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        fused_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        stages.append(
            timer.result(
                ok=True,
                model="deterministic_reconcile",
                artifacts=[str(fused_midi), str(fusion_path)],
                extra={
                    "canonical_notes": len(fused.notes),
                    "dropped_ghosts": len(fused.dropped_ghosts),
                    "unmatched_global": len(fused.unmatched_global),
                    "unmatched_specialist": len(fused.unmatched_specialist),
                    "keep_global_timing": True,
                },
            )
        )
        return fused

    def _interpreted(self, pipeline: UnderstandingPipeline, time_map: MusicalTimeMap) -> InterpretedPerformance:
        events = list(pipeline.last_quantized_events or [])
        notes = []
        for ev in events:
            onset = float(ev.start_beat)
            offset = onset + float(ev.duration_beats)
            notes.append(
                InterpretedNote(
                    source_note_id=ev.note_id,
                    beat_onset=onset,
                    beat_offset=offset,
                    instrument=ev.instrument.value if hasattr(ev.instrument, "value") else str(ev.instrument),
                    role=ev.role,
                    role_confidence=0.4 if ev.role else 0.0,
                    voice_candidate=int(ev.voice),
                    hand_candidate=ev.hand.value if ev.hand is not None else None,
                    phrase_id=ev.phrase_id,
                )
            )
        meter = None
        conf = None
        status = "ok"
        from timing.meter import meter_status

        if pipeline.last_meter_decision is not None:
            meter = pipeline.last_meter_decision.meter
            conf = pipeline.last_meter_decision.confidence
            status = meter_status(conf)
        return InterpretedPerformance(
            notes=notes,
            meter=meter,
            meter_confidence=conf,
            meter_status=status,
            extra={"time_map_source": time_map.source},
        )

    def _finish(
        self,
        source: Path,
        job_id: str,
        xml: str,
        pipeline: UnderstandingPipeline,
        stages: list[StageResult],
        warnings: list[str],
        time_map: MusicalTimeMap | None = None,
        interpreted: InterpretedPerformance | None = None,
        fusion: ReconciliationResult | None = None,
        rewrite_tempo: bool = False,
    ) -> OrchestratorResult:
        t0 = time.perf_counter()
        out_dir = source.parent / f"bp_{job_id}"
        manifest = ArtifactManifest(job_id=job_id)
        mapping = (
            (job_raw_midi_path(source, job_id), ArtifactKind.RAW_MIDI, "audio/midi", "full_mix", "TRANSCRIBE_GLOBAL"),
            (job_validated_midi_path(source, job_id), ArtifactKind.VALIDATED_MIDI, "audio/midi", "", "INTERPRET_SCORE"),
            (job_score_midi_path(source, job_id), ArtifactKind.SCORE_MIDI, "audio/midi", "", "EXPORT"),
            (job_fused_midi_path(source, job_id), ArtifactKind.PERFORMANCE_MIDI, "audio/midi", "", "RECONCILE"),
            (out_dir / f"{job_id}.musicxml", ArtifactKind.MUSICXML, "application/vnd.recordare.musicxml+xml", "", "EXPORT"),
            (out_dir / f"{job_id}.performance.json", ArtifactKind.PERFORMANCE_JSON, "application/json", "", "BUILD_PERFORMANCE"),
            (out_dir / f"{job_id}.debug.json", ArtifactKind.DEBUG_JSON, "application/json", "", "INTERPRET_SCORE"),
            (out_dir / f"{job_id}.fused.json", ArtifactKind.TRANSCRIPTION_JSON, "application/json", "", "RECONCILE"),
            (out_dir / f"{job_id}.fusion.json", ArtifactKind.FUSION_JSON, "application/json", "", "RECONCILE"),
            (out_dir / f"{job_id}_norm.wav", ArtifactKind.NORMALIZED_AUDIO, "audio/wav", "", "PREPROCESS"),
        )
        musicxml_path = out_dir / f"{job_id}.musicxml"
        if not musicxml_path.exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            musicxml_path.write_text(xml, encoding="utf-8")
        for path, kind, ctype, stem_id, stage in mapping:
            if Path(path).exists():
                manifest.add(
                    ref_for_file(
                        kind,
                        path,
                        content_type=ctype,
                        stem_id=stem_id,
                        storage_key=Path(path).name,
                        source_stage=stage,
                    )
                )
        for stem_wav in sorted(out_dir.glob(f"{job_id}.stem.*")):
            stem_id = stem_wav.name.split(".stem.", 1)[-1].rsplit(".", 1)[0]
            manifest.add(
                ref_for_file(
                    ArtifactKind.STEM_AUDIO,
                    stem_wav,
                    content_type="audio/wav",
                    stem_id=stem_id,
                    instrument=stem_id,
                    storage_key=stem_wav.name,
                    source_stage="SEPARATE",
                )
            )
        for stem_midi in sorted(out_dir.glob(f"{job_id}.raw.*.mid")):
            stem_id = stem_midi.name[len(job_id) + 5 : -4]
            manifest.add(
                ref_for_file(
                    ArtifactKind.RAW_MIDI,
                    stem_midi,
                    content_type="audio/midi",
                    stem_id=stem_id,
                    instrument=stem_id,
                    storage_key=stem_midi.name,
                    source_stage="TRANSCRIBE_STEMS",
                )
            )
        tempo_path = out_dir / f"{job_id}.tempo.json"
        if rewrite_tempo and time_map is not None:
            tempo_path.write_text(
                json.dumps(
                    {
                        "source": time_map.source,
                        "beat_times": list(time_map.beat_times),
                        "confidence": list(time_map.confidence),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if tempo_path.exists():
            manifest.add(
                ref_for_file(
                    ArtifactKind.TEMPO_JSON,
                    tempo_path,
                    content_type="application/json",
                    source_stage="ANALYZE_TIME",
                )
            )
        if interpreted is not None:
            interp_path = out_dir / f"{job_id}.interpretation.json"
            interp_path.write_text(json.dumps(interpreted.to_dict(), indent=2) + "\n", encoding="utf-8")
            manifest.add(
                ref_for_file(
                    ArtifactKind.SCORE_IR_JSON,
                    interp_path,
                    content_type="application/json",
                    storage_key=interp_path.name,
                    source_stage="INTERPRET_SCORE",
                )
            )
        stages.append(
            StageResult(StageName.EXPORT, ok=True, duration_ms=_ms(t0), model="notation_writer")
        )
        stages.append(
            StageResult(
                StageName.RENDER,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="PDF/SVG remain client OSMD; server MuseScore CLI is not wired",
            )
        )
        stages.append(StageResult(StageName.COMPLETE, ok=True, duration_ms=0.0, model="orchestrator"))
        provenance_path = out_dir / f"{job_id}.provenance.json"
        runtime = runtime_identification()
        extra_fields = live_provenance_fields(pipeline, stages)
        provenance_path.write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    **runtime,
                    "ensemble_render": runtime["ensemble_render_enabled"],
                    **extra_fields,
                    "stages": [s.to_dict() for s in stages],
                    "warnings": warnings,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        debug_path = out_dir / f"{job_id}.debug.json"
        if debug_path.exists():
            try:
                debug_payload = json.loads(debug_path.read_text(encoding="utf-8"))
                extra = dict(debug_payload.get("extra") or {})
                extra.update(runtime)
                debug_payload["extra"] = extra
                debug_path.write_text(json.dumps(debug_payload, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass
        manifest.add(
            ref_for_file(
                ArtifactKind.PROVENANCE_JSON,
                provenance_path,
                content_type="application/json",
                storage_key=provenance_path.name,
                source_stage="COMPLETE",
            )
        )
        if write_manifest_enabled():
            # Write without listing the manifest as one of its own artifacts.
            manifest_path = out_dir / f"{job_id}.manifest.json"
            manifest.write_json(manifest_path)
        return OrchestratorResult(
            musicxml=xml,
            stages=stages,
            manifest=manifest,
            interpreted=interpreted,
            warnings=warnings,
            time_map=time_map,
            fusion=fusion,
        )


def _skipped_sep() -> SeparationResult:
    return SeparationResult(
        stems=[],
        model="skipped",
        skipped=True,
        skip_reason="separator was not scheduled",
    )


def _separation_stage(timer: StageTimer, separation: SeparationResult, want_sep: bool) -> StageResult:
    if separation.error:
        return timer.result(
            ok=False,
            model=separation.model,
            requested_backend=separation.requested_backend or "http",
            actual_backend=separation.actual_backend,
            error=separation.error,
            warnings=list(separation.warnings),
            extra={"continued": True, "stem_count": len(separation.stems)},
        )
    return timer.result(
        ok=True,
        model=separation.model,
        requested_backend=separation.requested_backend or separation.model,
        actual_backend="" if separation.skipped else (separation.actual_backend or separation.model),
        skipped=separation.skipped,
        skip_reason=separation.skip_reason,
        warnings=list(separation.warnings),
        extra={"stem_count": len(separation.stems), "scheduled": want_sep},
        artifacts=[s.path for s in separation.stems],
    )


def _stem_stage(stem_rows) -> StageResult:
    if not stem_transcription_enabled():
        return StageResult(
            StageName.TRANSCRIBE_STEMS,
            ok=True,
            duration_ms=0.0,
            skipped=True,
            skip_reason="NEXTGEN_STEM_TRANSCRIPTION_ENABLED is off",
        )
    if not stem_rows:
        return StageResult(
            StageName.TRANSCRIBE_STEMS,
            ok=True,
            duration_ms=0.0,
            skipped=True,
            skip_reason="no pitched stems produced; refusing to invent stem MIDI",
        )
    errors = [row.error for row in stem_rows if row.error]
    successes = [row for row in stem_rows if not row.error]
    duration = sum(float(row.duration_ms) for row in stem_rows)
    return StageResult(
        StageName.TRANSCRIBE_STEMS,
        ok=bool(successes),
        duration_ms=duration,
        model="basic_pitch",
        requested_backend="basic_pitch",
        actual_backend="basic_pitch" if successes else "",
        fallback_used=bool(errors) and bool(successes),
        fallback_of="failed stem(s) dropped; remaining evidence kept",
        error="; ".join(errors),
        warnings=errors,
        extra={
            "stems": [
                {
                    "stem_id": row.stem_id,
                    "notes": len(row.notes),
                    "skipped": row.skipped,
                    "error": row.error,
                    "backend": row.backend,
                }
                for row in stem_rows
            ]
        },
        artifacts=[row.midi_path for row in stem_rows if row.midi_path],
    )


def _fusion_payload(fused: ReconciliationResult) -> dict:
    return {
        "schema": "fused-performance/v1",
        "notes": [
            {
                "note_id": item.note.note_id,
                "pitch": int(item.note.pitch),
                "onset_seconds": float(item.note.start_time),
                "offset_seconds": float(item.note.end_time),
                "velocity": int(item.note.velocity),
                "instrument": item.instrument,
                "instrument_confidence": item.instrument_confidence,
                "canonical_backend": item.canonical_backend,
                "evidence": [asdict(ev) for ev in item.evidence],
            }
            for item in fused.fused
        ],
        "dropped_ghosts": fused.diagnostics.get("dropped_ghosts", []),
        "unmatched_global": fused.diagnostics.get("unmatched_global", []),
        "unmatched_specialist": fused.diagnostics.get("unmatched_specialist", []),
        "diagnostics": fused.diagnostics,
    }
