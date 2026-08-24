"""Pipeline hook: run Gemini analysis and apply safe patches. Never fails the job."""

from __future__ import annotations

from dataclasses import dataclass, replace

from intelligence.cache import hash_bytes, hash_json
from intelligence.config import GeminiConfig, gemini_config
from intelligence.packet import build_analysis_packet
from intelligence.patches import apply_event_patches, apply_meta_patches, apply_note_patches
from intelligence.schemas import GeminiAnalysis
from intelligence.service import GeminiMusicAnalysisService
from intelligence.validator import MusicalCorrectionValidator
from audio_engine.normalizer import NormalizedAudio
from mir.cmr_builder import notes_to_events
from mir.types import (
    Chord,
    InstrumentPrediction,
    MusicalEvent,
    MusicalRole,
    NoteEvent,
    ScoreMeta,
    TempoMap,
)


@dataclass
class EnhancementResult:
    notes: list[NoteEvent]
    events: list[MusicalEvent]
    meta: ScoreMeta
    tempo_map: TempoMap
    analysis: GeminiAnalysis | None
    applied: int = 0
    rejected: int = 0
    skipped: bool = True


def maybe_enhance(
    *,
    job_id: str,
    notes: list[NoteEvent],
    events: list[MusicalEvent],
    meta: ScoreMeta,
    tempo_map: TempoMap,
    prediction: InstrumentPrediction | None,
    chords: list[Chord] | None = None,
    normalized: NormalizedAudio | None = None,
    pedal_events: list[tuple[float, int]] | None = None,
    role: MusicalRole | None = None,
    rebuild_events=None,
    cfg: GeminiConfig | None = None,
    service: GeminiMusicAnalysisService | None = None,
) -> EnhancementResult:
    """Return patched pipeline state. On any error, return the originals."""
    cfg = cfg or gemini_config()
    if not cfg.active:
        return EnhancementResult(
            notes=notes,
            events=events,
            meta=meta,
            tempo_map=tempo_map,
            analysis=None,
            skipped=True,
        )
    try:
        return _enhance(
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
            rebuild_events=rebuild_events,
            cfg=cfg,
            service=service or GeminiMusicAnalysisService(cfg),
        )
    except Exception as exc:
        print(f"[Gemini] layer skipped ({exc})")
        return EnhancementResult(
            notes=notes,
            events=events,
            meta=meta,
            tempo_map=tempo_map,
            analysis=None,
            skipped=True,
        )


def _enhance(
    *,
    job_id: str,
    notes: list[NoteEvent],
    events: list[MusicalEvent],
    meta: ScoreMeta,
    tempo_map: TempoMap,
    prediction: InstrumentPrediction | None,
    chords: list[Chord] | None,
    normalized: NormalizedAudio | None,
    pedal_events: list[tuple[float, int]] | None,
    role: MusicalRole | None,
    rebuild_events,
    cfg: GeminiConfig,
    service: GeminiMusicAnalysisService,
) -> EnhancementResult:
    duration = normalized.duration_sec if normalized is not None else 0.0
    sample_rate = normalized.sample_rate if normalized is not None else 0
    packet = build_analysis_packet(
        job_id=job_id,
        notes=notes,
        events=events,
        tempo_map=tempo_map,
        prediction=prediction,
        chords=chords,
        duration_seconds=duration,
        sample_rate=sample_rate,
        pedal_events=pedal_events,
    )
    audio_hash = ""
    if normalized is not None:
        audio_hash = hash_bytes(normalized.samples.tobytes())

    lite = service.analyse_music(
        packet, job_id=job_id, normalized=normalized, audio_hash=audio_hash
    )
    if lite.raw.get("_error"):
        extra = dict(meta.extra or {})
        extra["gemini"] = {
            "error": lite.raw.get("_error"),
            "applied": 0,
            "rejected": 0,
            "skipped": True,
        }
        return EnhancementResult(
            notes=notes,
            events=events,
            meta=replace(meta, extra=extra),
            tempo_map=tempo_map,
            analysis=lite,
            applied=0,
            rejected=0,
            skipped=True,
        )
    route = service.route(packet, lite)
    analysis = lite
    allow_deep = False
    if route.regional and route.windows:
        regional = service.analyse_uncertain_regions(
            packet,
            route.windows,
            job_id=job_id,
            normalized=normalized,
            audio_hash=audio_hash,
            model=cfg.reasoning_model if route.use_deep else cfg.default_model,
        )
        analysis = _merge_analysis(lite, regional)
        allow_deep = route.use_deep

    if not cfg.midi_validation:
        analysis.corrections = [
            c for c in analysis.corrections if c.type not in {"pitch", "timing"}
        ]
    if not cfg.structure_analysis:
        analysis.corrections = [
            c for c in analysis.corrections if c.type not in {"meter", "tempo", "key"}
        ]

    audio_conf = float(prediction.confidence) if prediction else 0.5
    validator = MusicalCorrectionValidator(cfg)
    accepted, rejected = validator.validate(
        analysis.corrections,
        notes,
        audio_feature_confidence=audio_conf,
        allow_deep=allow_deep,
    )
    patched_notes = apply_note_patches(notes, accepted)
    notes_changed = patched_notes != notes
    patched_events = events
    patched_meta, patched_tempo = apply_meta_patches(meta, tempo_map, accepted)
    if notes_changed or patched_tempo is not tempo_map:
        if rebuild_events is not None:
            patched_events = rebuild_events(patched_notes, patched_tempo, role)
        else:
            patched_events = notes_to_events(
                patched_notes,
                patched_tempo,
                role=role,
                instrument=prediction.instrument if prediction else patched_events[0].instrument,
                source_backend=patched_events[0].source_backend if patched_events else "unknown",
            )
    patched_events = apply_event_patches(patched_events, accepted, patched_tempo)
    extra = dict(patched_meta.extra or {})
    extra["gemini"] = {
        "model": analysis.model,
        "applied": len(accepted),
        "rejected": len(rejected),
        "complexity": route.complexity,
        "route": route.reason,
        "cache_hit": analysis.cache_hit,
        "overall_confidence": analysis.overall_confidence,
        "key": patched_meta.key_hint,
        "tempo_bpm": patched_meta.display_tempo_bpm,
        "corrections": [c.to_dict() for c in accepted],
    }
    patched_meta = replace(patched_meta, extra=extra)
    print(
        f"[Gemini] job={job_id} model={analysis.model} "
        f"applied={len(accepted)} rejected={len(rejected)} "
        f"route={route.reason} cache={analysis.cache_hit}"
    )
    return EnhancementResult(
        notes=patched_notes,
        events=patched_events,
        meta=patched_meta,
        tempo_map=patched_tempo,
        analysis=analysis,
        applied=len(accepted),
        rejected=len(rejected),
        skipped=False,
    )


def _merge_analysis(lite: GeminiAnalysis, extra: GeminiAnalysis) -> GeminiAnalysis:
    merged = list(lite.corrections)
    seen = {
        (c.type, round(c.time_start, 3), round(c.time_end, 3), json_key(c.existing_value))
        for c in merged
    }
    for corr in extra.corrections:
        key = (
            corr.type,
            round(corr.time_start, 3),
            round(corr.time_end, 3),
            json_key(corr.existing_value),
        )
        if key not in seen:
            merged.append(corr)
            seen.add(key)
    lite.corrections = merged
    if extra.overall_confidence:
        lite.overall_confidence = max(lite.overall_confidence, extra.overall_confidence)
    if extra.model:
        lite.model = extra.model
    return lite


def json_key(value: dict) -> str:
    return hash_json(value)
