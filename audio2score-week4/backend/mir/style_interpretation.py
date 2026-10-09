"""Style-aware interpretation applied after transcription, before spelling.

Production insertion point (existing pipeline, not a parallel path)::

    notes_to_events (performed seconds → beat coordinates)
      → resolve_layout (hands / voices)
      → interpret_for_notation  # this module
      → onset/duration candidate search
      → NotationPlan → MusicXML

Interpretation may rewrite score beats. It must not add, delete, transpose,
or reharmonize notes, and it must not touch source seconds or raw MIDI.

Arrangement is a later stage (``mir.arrangement``) that would consume the
interpreted score and emit a separate derived score.
"""

from __future__ import annotations

from typing import Any

from mir.interpretation_profile import InterpretationProfile, parse_interpretation_profile
from mir.swing import (
    InterpretationSpan,
    apply_written_timing,
    feel_limitations,
    feel_user_summary,
    infer_interpretation_spans,
    mark_spans_mapping,
    summarize_spans,
)
from mir.types import copy_event


def profile_from_settings(settings) -> InterpretationProfile:
    if settings is None:
        return InterpretationProfile()
    nested = getattr(settings, "interpretation_profile", None)
    if nested is not None:
        return parse_interpretation_profile(nested)
    if isinstance(settings, dict):
        if settings.get("interpretation_profile") is not None:
            return parse_interpretation_profile(settings.get("interpretation_profile"))
        return InterpretationProfile.from_dict(settings)
    return InterpretationProfile()


def interpret_for_notation(
    events,
    meter,
    settings=None,
    *,
    tempo_map=None,
) -> tuple[list, list[InterpretationSpan], dict[str, Any]]:
    """Map performed beat timing onto written coordinates when feel is clear.

    Returns (events, spans, summary). Event count, pitches, velocities, and
    note IDs are unchanged. ``start_time_sec`` / ``end_time_sec`` are unchanged.
    """
    source = list(events)
    identities = [
        (
            ev.note_id,
            ev.pitch,
            int(getattr(ev, "velocity", 0) or 0),
            getattr(ev, "start_time_sec", None),
            getattr(ev, "end_time_sec", None),
        )
        for ev in source
    ]
    profile = profile_from_settings(settings)
    spans = infer_interpretation_spans(
        source, meter, profile, tempo_map=tempo_map
    )
    interpretation = getattr(settings, "interpretation", None)
    if interpretation is None and isinstance(settings, dict):
        interpretation = settings.get("interpretation")
    interpretation_name = str(getattr(interpretation, "value", interpretation) or "").lower()
    # Literal keeps performed timing on the page. Feel is still detected so
    # the editor can show and correct it. Readable maps swing to written eighths.
    maps_written = interpretation_name != "literal"
    spans = mark_spans_mapping(spans, enabled=maps_written)
    interpreted = apply_written_timing(source, spans) if maps_written else list(source)
    if [
        (
            ev.note_id,
            ev.pitch,
            int(getattr(ev, "velocity", 0) or 0),
            getattr(ev, "start_time_sec", None),
            getattr(ev, "end_time_sec", None),
        )
        for ev in interpreted
    ] != identities:
        raise ValueError("Style interpretation mutated source note identity")
    if len(interpreted) != len(source):
        raise ValueError("Style interpretation changed note count")
    # Preserve source order; do not invent events.
    by_id = {ev.note_id: ev for ev in interpreted}
    ordered = []
    for original in source:
        mapped = by_id.get(original.note_id)
        ordered.append(mapped if mapped is not None else original)
    summary = summarize_spans(spans)
    summary["profile"] = profile.to_dict()
    summary["maps_written_timing"] = bool(maps_written and summary.get("maps_written_timing"))
    summary["user_summary"] = feel_user_summary(summary)
    summary["limitations"] = feel_limitations(meter, profile)
    return ordered, spans, summary


def stamp_performed_timing(events):
    """Record beat-space performance timing once, before any written mapping."""
    out = []
    for event in events:
        start = getattr(event, "performed_start_beat", None)
        dur = getattr(event, "performed_duration_beats", None)
        if start is not None and dur is not None:
            out.append(event)
            continue
        out.append(
            copy_event(
                event,
                performed_start_beat=float(event.start_beat),
                performed_duration_beats=float(event.duration_beats),
            )
        )
    return out
