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

# Legacy single-reference filenames (Checkpoint 7)
REFERENCE_CANDIDATES = (
    "reference.mid",
    "reference.midi",
    "ref.mid",
)

# Preferred two-reference filenames (Checkpoint 7B)
REFERENCE_RAW_CANDIDATES = (
    "reference_raw.mid",
    "reference_raw.midi",
)

REFERENCE_SCORE_CANDIDATES = (
    "reference_score.mid",
    "reference_score.midi",
)

MANIFEST_NAMES = (
    "case.yaml",
    "case.yml",
    "case.json",
)

SPLITS = ("development", "holdout", "real_world")

# Stages compared against the raw performance reference
RAW_REFERENCE_STAGES = (
    "transcription",
    "post_cleaner",
    "post_piano",
)

# Stages compared against the score / quantized reference (when available)
SCORE_REFERENCE_STAGES = (
    "structured",
)
