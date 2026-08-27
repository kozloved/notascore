"""Checkpoint 9A transcription experiment matrix.

Opt-in only. Does not modify production transcription defaults or pipeline.
"""

from __future__ import annotations

from evaluation.experiments.config import ExperimentConfig, PreprocessConfig, TranscriptionParams
from evaluation.experiments.registry import (
    list_experiments,
    get_experiment,
    all_experiment_names,
)

__all__ = [
    "ExperimentConfig",
    "PreprocessConfig",
    "TranscriptionParams",
    "list_experiments",
    "get_experiment",
    "all_experiment_names",
]

__version__ = "0.1.0"
