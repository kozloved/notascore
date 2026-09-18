"""Recompute notation from an existing performance without re-transcribing audio.

Original MIDI bytes and the performance snapshot stay untouched. Only the
derived score artifacts are rewritten. Cache identity includes the MIDI
checksum, algorithm version, and notation settings.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from mir.cmr_builder import build_score_meta, notes_to_events
from mir.midi_ingest import ingest_midi
from mir.notation_settings import (
    NotationSettings,
    parse_notation_settings,
    settings_for_reset,
)
from mir.performance import PerformanceSnapshot
from mir.pipeline_config import QuantizationMode
from mir.types import InstrumentKind, ScoreMeta
from notation_engine.writer import NotationWriter


@dataclass
class NotationRegenResult:
    musicxml: str
    settings: NotationSettings
    cache_key: str
    midi_sha256: str
    source_note_count: int
    transcribed: bool = False
    decisions: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _layout_from_decisions(events, decisions):
    from mir.types import Hand, copy_event

    by_id = {row.get("note_id"): row for row in decisions or [] if row.get("note_id")}
    if not by_id:
        return events
    out = []
    for ev in events:
        row = by_id.get(ev.note_id)
        if not row:
            out.append(ev)
            continue
        hand_value = row.get("hand") or ev.hand.value
        try:
            hand = Hand(hand_value)
        except ValueError:
            hand = ev.hand
        musical = row.get("musical_voice")
        out.append(
            copy_event(
                ev,
                hand=hand,
                voice=int(row.get("printed_voice", row.get("voice", ev.voice)) or 0),
                musical_voice=None if musical is None else int(musical),
                voice_assigned=True,
                voice_provenance=row.get("voice_provenance") or ev.voice_provenance or "supplied",
            )
        )
    return out


def recompute_notation(
    *,
    midi_bytes: bytes,
    settings: NotationSettings | dict | None = None,
    performance: PerformanceSnapshot | None = None,
    meter: str | None = None,
    prior_decisions: list[dict] | None = None,
    tempo_map=None,
    display_bpm: int | None = None,
) -> NotationRegenResult:
    """Build a new score from frozen performance MIDI.

    Never calls an audio transcriber. Raises if the MIDI checksum does not
    match a provided performance snapshot.
    """
    settings = parse_notation_settings(settings)
    if settings.meter and meter and settings.meter != meter:
        raise ValueError(
            f"Contradictory meter: settings {settings.meter} vs request {meter}."
        )
    meter_hint = settings.meter or meter
    if performance is None:
        import io
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(io.BytesIO(midi_bytes))
        from mir.performance import snapshot_midi

        performance = snapshot_midi(midi, midi_bytes, backend="midi")
    else:
        performance.verify_midi(midi_bytes)

    ingested = None
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mid") as handle:
        handle.write(midi_bytes)
        handle.flush()
        ingested = ingest_midi(Path(handle.name))

    notes = list(performance.to_notes())
    if not notes:
        notes = [n.ensure_ids(i) for i, n in enumerate(ingested.notes)]
    source_ids = [n.note_id for n in notes]
    mapper = tempo_map or ingested.tempo_map
    backend = performance.source_backend or "midi"
    events = notes_to_events(notes, mapper, source_backend=backend)
    events = _layout_from_decisions(events, prior_decisions)
    instrument = notes[0].instrument if notes else InstrumentKind.PIANO
    meta = build_score_meta(
        mapper,
        instrument,
        [],
        display_bpm=display_bpm or round(mapper.bpm_at(0)),
        instrument_confidence=0.9,
        time_sig_hint=meter_hint or ingested.time_sig_hint,
    )
    meta.extra = {
        **(meta.extra or {}),
        "notation_settings": settings.to_dict(),
        "pedal_events": list(ingested.pedal_events or []),
        "preserve_midi_tempo": True,
    }
    writer = NotationWriter()
    score = writer.write_from_events_direct(
        events, meta, quantization_mode=QuantizationMode.PERFORMANCE
    )
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        path = Path(tmp) / "score.musicxml"
        writer._export_musicxml(score, path)
        xml = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(midi_bytes).hexdigest()
    if [n.note_id for n in notes] != source_ids:
        raise ValueError("Notation regen mutated source note IDs")
    performance.verify_midi(midi_bytes)
    return NotationRegenResult(
        musicxml=xml,
        settings=settings,
        cache_key=settings.cache_key(digest),
        midi_sha256=digest,
        source_note_count=len(notes),
        transcribed=False,
        decisions=list(writer.last_quantization_decisions or []),
        summary=dict(writer.last_quantization_summary or {}),
    )


def recompute_job_dir(out_dir: Path, job_id: str, settings: NotationSettings | dict | None = None) -> NotationRegenResult:
    """Rewrite derived score files in an existing job directory."""
    out_dir = Path(out_dir)
    raw_path = out_dir / f"{job_id}.raw.mid"
    snap_path = out_dir / f"{job_id}.performance.json"
    debug_path = out_dir / f"{job_id}.debug.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw MIDI for job {job_id}")
    midi_bytes = raw_path.read_bytes()
    performance = PerformanceSnapshot.read_json(snap_path) if snap_path.exists() else None
    prior = None
    if debug_path.exists():
        debug = json.loads(debug_path.read_text(encoding="utf-8"))
        extra = debug.get("extra") or debug
        prior = extra.get("quantization_decisions") or extra.get("quantization_summary")
        if isinstance(prior, dict):
            prior = None
    result = recompute_notation(
        midi_bytes=midi_bytes,
        settings=settings,
        performance=performance,
        prior_decisions=prior if isinstance(prior, list) else None,
    )
    after = raw_path.read_bytes()
    if hashlib.sha256(after).hexdigest() != result.midi_sha256:
        raise ValueError("Notation regen changed original MIDI bytes")
    (out_dir / f"{job_id}.musicxml").write_text(result.musicxml, encoding="utf-8")
    (out_dir / f"{job_id}.notation_settings.json").write_text(
        json.dumps(
            {
                "notation_settings": result.settings.to_dict(),
                "algorithm_version": result.settings.algorithm_version,
                "notation_cache_key": result.cache_key,
                "midi_sha256": result.midi_sha256,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def reset_settings() -> NotationSettings:
    return settings_for_reset()
