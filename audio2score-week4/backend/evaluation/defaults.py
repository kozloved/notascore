"""Default tolerances and regression thresholds for evaluation."""

from __future__ import annotations

# Musical note matching (seconds / semitones)
ONSET_TOLERANCE_SEC = 0.05
OFFSET_TOLERANCE_SEC = 0.10
PITCH_TOLERANCE_SEMITONES = 0

# Tempo comparison
TEMPO_MATCH_TOLERANCE_BPM = 3.0

# Baseline comparison: ignore tiny float noise on F1
BASELINE_F1_EPSILON = 0.01

# Primary metric key used for IMPROVED / REGRESSED / UNCHANGED
PRIMARY_METRIC = "onset_pitch_f1"

# Audio filename candidates (first existing wins)
AUDIO_CANDIDATES = (
    "input.wav",
    "input.mp3",
    "input.flac",
    "input.ogg",
    "input.m4a",
    "input.mid",
    "input.midi",
    "audio.wav",
)

REFERENCE_CANDIDATES = (
    "reference.mid",
    "reference.midi",
    "ref.mid",
)

MANIFEST_NAMES = (
    "case.yaml",
    "case.yml",
    "case.json",
)

SPLITS = ("development", "holdout", "real_world")
