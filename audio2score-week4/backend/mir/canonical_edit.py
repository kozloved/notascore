"""Versioned editable performance contract shared by API and export."""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 2

# Supported editor limits. Exceeding these must raise, never silently clamp.
MAX_TRACKS = 16
MAX_VOICES = 16
MAX_NOTE_DURATION_BEATS = 512.0
MAX_TEMPO_CURVE_POINTS = 8192
MIDI_PERCUSSION_CHANNEL = 9
MIDI_CHANNEL_CAPACITY = 15  # 16 channels minus percussion


def editable_contract_meta(
    *,
    note_source: str = "full_mix",
    selected_meter: str = "4/4",
    provenance: str | None = "performance",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "note_source": note_source,
        "selected_meter": selected_meter,
        "provenance": provenance,
        "limits": {
            "max_tracks": MAX_TRACKS,
            "max_voices": MAX_VOICES,
            "max_note_duration_beats": MAX_NOTE_DURATION_BEATS,
            "max_tempo_curve_points": MAX_TEMPO_CURVE_POINTS,
            "midi_percussion_channel": MIDI_PERCUSSION_CHANNEL,
            "midi_channel_capacity": MIDI_CHANNEL_CAPACITY,
        },
    }
