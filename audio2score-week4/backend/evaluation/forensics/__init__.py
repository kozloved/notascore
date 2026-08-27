"""Checkpoint 8 transcription forensics — read-only diagnostic package.

Does not modify production transcription algorithms.
"""

from __future__ import annotations

from evaluation.forensics.analyze import analyze_case, analyze_corpus
from evaluation.forensics.classify import classify_notes, matching_strategy_doc

__all__ = [
    "analyze_case",
    "analyze_corpus",
    "classify_notes",
    "matching_strategy_doc",
]
