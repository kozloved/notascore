"""Stage orchestrator. Existing UnderstandingPipeline remains the score engine."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from engine.artifacts import ArtifactKind, ArtifactManifest, ref_for_file
from engine.flags import write_manifest_enabled
from engine.ir import InterpretedNote, InterpretedPerformance
from engine.stages import StageName, StageResult
from mir.midi_ingest import ingest_midi, is_midi_path
from mir.pipeline import UnderstandingPipeline
from mir.raw_midi import (
    job_raw_midi_path,
    job_score_midi_path,
    job_validated_midi_path,
)
from separation.service import get_separator
from timing.tempo_map import MusicalTimeMap
from transcription_fed.reconcile import reconcile_transcriptions


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


@dataclass
class OrchestratorResult:
    musicxml: str
    stages: list[StageResult]
    manifest: ArtifactManifest
    interpreted: InterpretedPerformance | None = None
    warnings: list[str] = field(default_factory=list)
    time_map: MusicalTimeMap | None = None

    def stage(self, name: StageName) -> StageResult | None:
        for row in self.stages:
            if row.name == name:
                return row
        return None


class PipelineOrchestrator:
    """Typed stages around the current production engine.

    SEPARATE / Transkun / Beat This! are recorded skips until licensed.
    Full-mix and stem transcription are parallel *slots*; stem AMT only
    runs when separation actually produced audio.
    """

    def run(self, source: str | Path, job_id: str, *, meter: str | None = None) -> OrchestratorResult:
        source = Path(source)
        if is_midi_path(source):
            return self.run_midi(source, job_id, meter=meter)
        return self.run_audio(source, job_id)

    def run_audio(self, audio_path: str | Path, job_id: str) -> OrchestratorResult:
        audio_path = Path(audio_path)
        stages: list[StageResult] = []
        warnings: list[str] = []

        stages.append(
            StageResult(
                StageName.INGEST,
                ok=True,
                duration_ms=0.0,
                model="audio_file",
                extra={"path": str(audio_path)},
            )
        )
        t0 = time.perf_counter()
        separation = get_separator().separate(str(audio_path))
        stages.append(
            StageResult(
                StageName.SEPARATE,
                ok=True,
                duration_ms=_ms(t0),
                model=separation.model,
                skipped=separation.skipped,
                skip_reason=separation.skip_reason,
                warnings=list(separation.warnings),
                extra={"stem_count": len(separation.stems)},
            )
        )
        if separation.skipped:
            warnings.append(separation.skip_reason)
        stages.append(
            StageResult(
                StageName.PREPROCESS,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="preprocess currently runs inside UnderstandingPipeline",
            )
        )
        stages.append(
            StageResult(
                StageName.ANALYZE_AUDIO,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="Beat This! disabled; existing tracker runs inside UnderstandingPipeline",
            )
        )
        stages.append(
            StageResult(
                StageName.TRANSCRIBE_STEMS,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="no stems produced; refusing to invent stem MIDI",
            )
        )
        t1 = time.perf_counter()
        pipeline = UnderstandingPipeline()
        xml = pipeline.transcribe(audio_path, job_id)
        stages.append(
            StageResult(
                StageName.TRANSCRIBE_GLOBAL,
                ok=True,
                duration_ms=_ms(t1),
                model=getattr(pipeline.config, "backend", "understanding"),
                extra={"bundled_with": "existing_understanding_pipeline"},
            )
        )
        stages.append(
            StageResult(
                StageName.RECONCILE,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="single global transcriber; no specialist stream",
            )
        )
        snapshot = pipeline.last_performance_snapshot
        stages.append(
            StageResult(
                StageName.BUILD_PERFORMANCE,
                ok=True,
                duration_ms=0.0,
                model="PerformanceSnapshot",
                extra={"midi_sha256": getattr(snapshot, "midi_sha256", None)},
            )
        )
        stages.append(
            StageResult(
                StageName.ANALYZE_TIME,
                ok=True,
                duration_ms=0.0,
                skipped=True,
                skip_reason="audio time map remains inside UnderstandingPipeline until Beat This! lands",
            )
        )
        stages.append(
            StageResult(
                StageName.INTERPRET_SCORE,
                ok=True,
                duration_ms=0.0,
                model=str(pipeline.config.quantization_mode.value),
                extra={"bundled_with": "existing_understanding_pipeline"},
            )
        )
        return self._finish(audio_path, job_id, xml, pipeline, stages, warnings)

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
        separation = get_separator().separate(str(midi_path))
        stages.append(
            StageResult(
                StageName.SEPARATE,
                ok=True,
                duration_ms=_ms(t1),
                model=separation.model,
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
        )
        return result

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
    ) -> OrchestratorResult:
        t0 = time.perf_counter()
        out_dir = source.parent / f"bp_{job_id}"
        manifest = ArtifactManifest(job_id=job_id)
        mapping = (
            (job_raw_midi_path(source, job_id), ArtifactKind.RAW_MIDI, "audio/midi"),
            (job_validated_midi_path(source, job_id), ArtifactKind.VALIDATED_MIDI, "audio/midi"),
            (job_score_midi_path(source, job_id), ArtifactKind.SCORE_MIDI, "audio/midi"),
            (out_dir / f"{job_id}.musicxml", ArtifactKind.MUSICXML, "application/vnd.recordare.musicxml+xml"),
            (out_dir / f"{job_id}.performance.json", ArtifactKind.PERFORMANCE_JSON, "application/json"),
            (out_dir / f"{job_id}.debug.json", ArtifactKind.DEBUG_JSON, "application/json"),
        )
        if not (out_dir / f"{job_id}.musicxml").exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{job_id}.musicxml").write_text(xml, encoding="utf-8")
        for path, kind, ctype in mapping:
            if Path(path).exists():
                manifest.add(ref_for_file(kind, path, content_type=ctype))
        if time_map is not None:
            tempo_path = out_dir / f"{job_id}.tempo.json"
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
            manifest.add(ref_for_file(ArtifactKind.TEMPO_JSON, tempo_path, content_type="application/json"))
        if interpreted is not None:
            interp_path = out_dir / f"{job_id}.interpretation.json"
            interp_path.write_text(json.dumps(interpreted.to_dict(), indent=2) + "\n", encoding="utf-8")
            manifest.add(
                ref_for_file(ArtifactKind.SCORE_IR_JSON, interp_path, content_type="application/json")
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
        provenance_path.write_text(
            json.dumps({"job_id": job_id, "stages": [s.to_dict() for s in stages]}, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest.add(ref_for_file(ArtifactKind.PROVENANCE_JSON, provenance_path, content_type="application/json"))
        if write_manifest_enabled():
            manifest.write_json(out_dir / f"{job_id}.manifest.json")
            manifest.add(
                ref_for_file(
                    ArtifactKind.MANIFEST_JSON,
                    out_dir / f"{job_id}.manifest.json",
                    content_type="application/json",
                )
            )
        return OrchestratorResult(
            musicxml=xml,
            stages=stages,
            manifest=manifest,
            interpreted=interpreted,
            warnings=warnings,
            time_map=time_map,
        )
