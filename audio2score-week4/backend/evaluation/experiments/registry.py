"""Named experiment registry for Checkpoint 9A.

Axes:
  A — audio representation (independent variants)
  B — Basic Pitch parameters (independent variants)
  C — limited justified combinations (filled after axis ranking, or predeclared candidates)

Redundant audio variants that duplicate production behavior are registered with
skip_reason so the runner can document the skip without running them.
"""

from __future__ import annotations

from evaluation.experiments.config import (
    PRODUCTION_FRAME_THRESHOLD,
    PRODUCTION_MIN_NOTE_LENGTH_MS,
    PRODUCTION_ONSET_THRESHOLD,
    PRODUCTION_SAMPLE_RATE,
    ExperimentConfig,
    PreprocessConfig,
    TranscriptionParams,
    production_preprocess,
)


def _bp(
    *,
    onset: float | None = None,
    frame: float | None = None,
    min_ms: float | None = None,
) -> TranscriptionParams:
    return TranscriptionParams(
        onset_threshold=PRODUCTION_ONSET_THRESHOLD if onset is None else onset,
        frame_threshold=PRODUCTION_FRAME_THRESHOLD if frame is None else frame,
        minimum_note_length=(
            PRODUCTION_MIN_NOTE_LENGTH_MS if min_ms is None else min_ms
        ),
    )


def _build_registry() -> dict[str, ExperimentConfig]:
    prod_pp = production_preprocess()
    prod_bp = TranscriptionParams.production()

    # --- Baseline ---
    baseline = ExperimentConfig(
        name="basic_pitch_baseline",
        axis="baseline",
        description=(
            "Control: production AudioNormalizer (mono, DC remove, 22050 Hz, "
            "peak 0.95) + production Basic Pitch defaults "
            f"(onset={PRODUCTION_ONSET_THRESHOLD}, frame={PRODUCTION_FRAME_THRESHOLD}, "
            f"min_note_ms={PRODUCTION_MIN_NOTE_LENGTH_MS})."
        ),
        preprocess=prod_pp,
        transcription=prod_bp,
    )

    # --- Axis A: audio (transcription fixed at production) ---
    a1 = ExperimentConfig(
        name="A1_mono_native",
        axis="audio",
        description=(
            "Mono mixdown only; keep native sample rate; no peak normalize; "
            "no DC remove; no silence trim."
        ),
        preprocess=PreprocessConfig(
            name="A1_mono_native",
            mono=True,
            target_sr=None,
            peak_normalize=False,
            remove_dc=False,
            trim_silence=False,
        ),
        transcription=prod_bp,
    )
    a2 = ExperimentConfig(
        name="A2_mono_peak_native",
        axis="audio",
        description="Mono mixdown + peak normalize to 0.95; keep native sample rate.",
        preprocess=PreprocessConfig(
            name="A2_mono_peak_native",
            mono=True,
            target_sr=None,
            peak_normalize=True,
            remove_dc=True,
            trim_silence=False,
        ),
        transcription=prod_bp,
    )
    # A3: resample-only to 22050. Production already resamples to 22050 AND peak-
    # normalizes. A pure "resample to 22050" without peak differs from A0, so we
    # keep it as an isolatable variant (mono+DC+22050, no peak).
    a3 = ExperimentConfig(
        name="A3_resample_22050",
        axis="audio",
        description=(
            "Mono + DC remove + resample to 22050 Hz without peak normalization. "
            "Isolates resample vs production (production also peak-normalizes)."
        ),
        preprocess=PreprocessConfig(
            name="A3_resample_22050",
            mono=True,
            target_sr=PRODUCTION_SAMPLE_RATE,
            peak_normalize=False,
            remove_dc=True,
            trim_silence=False,
        ),
        transcription=prod_bp,
    )
    a4 = ExperimentConfig(
        name="A4_resample_44100",
        axis="audio",
        description=(
            "Mono + DC remove + resample to 44100 Hz + peak normalize. "
            "Basic Pitch will reload at 22050 internally."
        ),
        preprocess=PreprocessConfig(
            name="A4_resample_44100",
            mono=True,
            target_sr=44100,
            peak_normalize=True,
            remove_dc=True,
            trim_silence=False,
        ),
        transcription=prod_bp,
    )
    a5 = ExperimentConfig(
        name="A5_trim_silence",
        axis="audio",
        description=(
            "Production normalizer path with leading/trailing silence trim enabled. "
            "WARNING: trim can shift absolute onsets; reported for diagnostics only "
            "if duration changes. Prefer pad-preserving edge trim in preprocess."
        ),
        preprocess=PreprocessConfig(
            name="A5_trim_silence",
            use_production_normalizer=False,
            mono=True,
            target_sr=PRODUCTION_SAMPLE_RATE,
            peak_normalize=True,
            remove_dc=True,
            trim_silence=True,
        ),
        transcription=prod_bp,
    )

    # --- Axis B: Basic Pitch (preprocess fixed at production) ---
    b1 = ExperimentConfig(
        name="B1_lower_onset",
        axis="basic_pitch",
        description="Slightly lower onset threshold (0.5); frame stays 0.4.",
        preprocess=prod_pp,
        transcription=_bp(onset=0.5),
    )
    b2 = ExperimentConfig(
        name="B2_higher_onset",
        axis="basic_pitch",
        description="Slightly higher onset threshold (0.7); frame stays 0.4.",
        preprocess=prod_pp,
        transcription=_bp(onset=0.7),
    )
    b3 = ExperimentConfig(
        name="B3_lower_frame",
        axis="basic_pitch",
        description="Slightly lower frame threshold (0.3); onset stays 0.6.",
        preprocess=prod_pp,
        transcription=_bp(frame=0.3),
    )
    b4 = ExperimentConfig(
        name="B4_higher_frame",
        axis="basic_pitch",
        description="Slightly higher frame threshold (0.5); onset stays 0.6.",
        preprocess=prod_pp,
        transcription=_bp(frame=0.5),
    )
    b5 = ExperimentConfig(
        name="B5_lower_min_note",
        axis="basic_pitch",
        description="Lower minimum note length to 58.0 ms (≈ half production 127.7).",
        preprocess=prod_pp,
        transcription=_bp(min_ms=58.0),
    )
    b6 = ExperimentConfig(
        name="B6_lower_onset_frame",
        axis="basic_pitch",
        description=(
            "Moderately lower onset+frame (0.5 / 0.3) — Basic Pitch library defaults."
        ),
        preprocess=prod_pp,
        transcription=_bp(onset=0.5, frame=0.3),
    )
    b7 = ExperimentConfig(
        name="B7_conservative_higher",
        axis="basic_pitch",
        description="Conservative higher thresholds (onset 0.7, frame 0.5).",
        preprocess=prod_pp,
        transcription=_bp(onset=0.7, frame=0.5),
    )

    # --- Axis C: predeclared combination candidates ---
    # Selection rationale is refined after individual axes; these cover the
    # most plausible complementarity without a full Cartesian product.
    c1 = ExperimentConfig(
        name="C1_mono_native_lower_onset_frame",
        axis="combined",
        description="A1 mono-native + B6 lower onset/frame (0.5/0.3).",
        preprocess=a1.preprocess,
        transcription=_bp(onset=0.5, frame=0.3),
        parent_experiments=("A1_mono_native", "B6_lower_onset_frame"),
    )
    c2 = ExperimentConfig(
        name="C2_mono_peak_lower_onset",
        axis="combined",
        description="A2 mono+peak native + B1 lower onset (0.5).",
        preprocess=a2.preprocess,
        transcription=_bp(onset=0.5),
        parent_experiments=("A2_mono_peak_native", "B1_lower_onset"),
    )
    c3 = ExperimentConfig(
        name="C3_resample_44100_lower_onset_frame",
        axis="combined",
        description="A4 44100 preprocess + B6 lower onset/frame.",
        preprocess=a4.preprocess,
        transcription=_bp(onset=0.5, frame=0.3),
        parent_experiments=("A4_resample_44100", "B6_lower_onset_frame"),
    )
    c4 = ExperimentConfig(
        name="C4_mono_native_lower_min_note",
        axis="combined",
        description="A1 mono-native + B5 lower min note length.",
        preprocess=a1.preprocess,
        transcription=_bp(min_ms=58.0),
        parent_experiments=("A1_mono_native", "B5_lower_min_note"),
    )
    c5 = ExperimentConfig(
        name="C5_production_audio_library_defaults",
        axis="combined",
        description=(
            "Production audio + library-like thresholds with lower min note "
            "(onset 0.5, frame 0.3, min_ms 58)."
        ),
        preprocess=prod_pp,
        transcription=_bp(onset=0.5, frame=0.3, min_ms=58.0),
        parent_experiments=("basic_pitch_baseline", "B6_lower_onset_frame", "B5_lower_min_note"),
    )
    c6 = ExperimentConfig(
        name="C6_trim_lower_onset_frame",
        axis="combined",
        description="A5 silence-aware preprocess + B6 lower onset/frame.",
        preprocess=a5.preprocess,
        transcription=_bp(onset=0.5, frame=0.3),
        parent_experiments=("A5_trim_silence", "B6_lower_onset_frame"),
    )

    # Alternative backend note — classical_dsp exists but is not auto-run as a
    # full substitute unless explicitly requested; document as future candidate.
    alt_doc = ExperimentConfig(
        name="ALT_classical_dsp_future",
        axis="alternative",
        description=(
            "Repository already contains ClassicalDspBackend. Not executed in "
            "Checkpoint 9A by default — future candidate for Checkpoint 9B option C."
        ),
        preprocess=prod_pp,
        transcription=prod_bp,
        skip_reason=(
            "Alternative backend deferred: Checkpoint 9A focuses on Basic Pitch path; "
            "classical_dsp is available at adapters/classical_dsp_backend.py."
        ),
    )

    configs = [
        baseline,
        a1,
        a2,
        a3,
        a4,
        a5,
        b1,
        b2,
        b3,
        b4,
        b5,
        b6,
        b7,
        c1,
        c2,
        c3,
        c4,
        c5,
        c6,
        alt_doc,
    ]
    return {c.name: c for c in configs}


_REGISTRY: dict[str, ExperimentConfig] | None = None


def get_registry() -> dict[str, ExperimentConfig]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def list_experiments(*, include_skipped: bool = True) -> list[ExperimentConfig]:
    regs = list(get_registry().values())
    if not include_skipped:
        regs = [c for c in regs if not c.is_skipped]
    return regs


def all_experiment_names(*, include_skipped: bool = True) -> list[str]:
    return [c.name for c in list_experiments(include_skipped=include_skipped)]


def get_experiment(name: str) -> ExperimentConfig:
    registry = get_registry()
    if name not in registry:
        known = ", ".join(sorted(registry))
        raise KeyError(f"Unknown experiment {name!r}. Known: {known}")
    return registry[name]


def resolve_experiment_selection(name: str) -> list[ExperimentConfig]:
    """Resolve ``all`` or a single experiment name to runnable configs."""
    if name == "all":
        return list_experiments(include_skipped=False)
    cfg = get_experiment(name)
    return [cfg]
