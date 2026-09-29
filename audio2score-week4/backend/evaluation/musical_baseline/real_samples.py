"""Manifest-registered real-job review cases for the musical baseline package.

Real samples are separate from the fixed 15-case synthetic P1 candidate set.
Comparison model is **original versus corrected** — not algorithm v1 versus v2.
Missing engine identity, audio, source-note IDs, or reference labels stay
explicitly unknown/missing. Does not invent jobs or human reviews.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.musical_baseline.catalog import REVIEW_DIMENSIONS
from evaluation.musical_baseline.reviews import (
    CASE_REPORT_NAME,
    COMPLETION_CRITERIA,
    FINGERPRINT_NAME,
    REVIEW_FORM_NAME,
    REVIEW_JSON_NAME,
    SCHEMA_VERSION,
    ArtifactProbe,
    ReviewValidation,
    load_review,
    review_has_human_input,
    sha256_bytes,
    sha256_text,
    stable_musicxml_digest,
    validate_review,
    write_review_form_if_absent,
    write_review_if_absent,
)

REAL_SAMPLES_DIRNAME = "real_samples"
MANIFEST_NAME = "manifest.json"
CASE_MANIFEST_NAME = "case_manifest.json"
CORRECTIONS_NAME = "corrections.json"
NOTE_INDEX_NAME = "note_index.json"

# Original-vs-corrected artifact map (not algorithm v1/v2).
REAL_CORE_ARTIFACT_FILES = {
    "original_musicxml_sha256": ("original.musicxml", "musicxml"),
}
REAL_OPTIONAL_ARTIFACT_FILES = {
    "input_midi_sha256": ("input.mid", "bytes"),
    "original_score_midi_sha256": ("original.score.mid", "bytes"),
    "corrected_musicxml_sha256": ("corrected.musicxml", "musicxml"),
    "corrected_score_midi_sha256": ("corrected.score.mid", "bytes"),
    "audio_sha256": ("audio.bin", "bytes"),  # placeholder; resolved via probe
    "corrections_sha256": (CORRECTIONS_NAME, "bytes"),
}
REAL_CONTENT_HASH_FIELDS = tuple(REAL_CORE_ARTIFACT_FILES) + tuple(
    k for k in REAL_OPTIONAL_ARTIFACT_FILES if k != "audio_sha256"
)
REAL_METADATA_BINDING_FIELDS = (
    "comparison_model",
    "case_kind",
    "settings_digest",
)
REAL_BINDING_FIELDS = (
    "original_musicxml_sha256",
    "original_score_midi_sha256",
    "corrected_musicxml_sha256",
    "corrected_score_midi_sha256",
    "input_midi_sha256",
    "audio_sha256",
    "corrections_sha256",
) + REAL_METADATA_BINDING_FIELDS

REAL_OPTIONAL_NULL_FIELDS = frozenset(
    {
        "original_score_midi_sha256",
        "corrected_musicxml_sha256",
        "corrected_score_midi_sha256",
        "input_midi_sha256",
        "audio_sha256",
        "corrections_sha256",
    }
)

AUDIO_CANDIDATES = (
    "audio.wav",
    "audio.mp3",
    "audio.flac",
    "audio.m4a",
    "original.wav",
    "source.wav",
)

BUNDLE_ALIASES = {
    "original.musicxml": (
        "original.musicxml",
        "unedited.musicxml",
        "automatic.musicxml",
    ),
    "original.score.mid": (
        "original.score.mid",
        "unedited.score.mid",
        "automatic.score.mid",
        "score.mid",
    ),
    "corrected.musicxml": (
        "corrected.musicxml",
        "edited.musicxml",
    ),
    "corrected.score.mid": (
        "corrected.score.mid",
        "edited.score.mid",
    ),
    "input.mid": (
        "input.mid",
        "raw.mid",
        "source.mid",
        "validated.mid",
    ),
    CORRECTIONS_NAME: (CORRECTIONS_NAME, "edits.json", "operations.json"),
    NOTE_INDEX_NAME: (NOTE_INDEX_NAME,),
}


def real_samples_root(package_dir: Path) -> Path:
    return Path(package_dir) / REAL_SAMPLES_DIRNAME


def manifest_path(package_dir: Path) -> Path:
    return real_samples_root(package_dir) / MANIFEST_NAME


def case_dir_for(package_dir: Path, example_id: str) -> Path:
    return real_samples_root(package_dir) / example_id


def _status_token(present: bool, *, value: Any = None) -> dict[str, Any]:
    if present:
        out: dict[str, Any] = {"status": "present"}
        if value is not None:
            out["value"] = value
        return out
    return {"status": "missing"}


def _unknown(field: str) -> dict[str, Any]:
    return {"status": "unknown", "field": field}


def _find_first(directory: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = directory / name
        if path.is_file():
            return path
    return None


def _audio_path(case_dir: Path) -> Path | None:
    for name in AUDIO_CANDIDATES:
        path = case_dir / name
        if path.is_file():
            return path
    # Any audio.* already copied with a stable name.
    for path in sorted(case_dir.glob("audio.*")):
        if path.is_file():
            return path
    return None


def load_package_manifest(package_dir: Path) -> dict[str, Any]:
    path = manifest_path(package_dir)
    if not path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "cases": [],
            "note": (
                "Real-job cases registered under real_samples/. Separate from "
                "the synthetic 15-case P1 candidate set."
            ),
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be an object")
    cases = data.get("cases")
    if cases is None:
        data["cases"] = []
    elif not isinstance(cases, list):
        raise ValueError(f"{path} cases must be a list")
    return data


def save_package_manifest(package_dir: Path, manifest: dict[str, Any]) -> Path:
    root = real_samples_root(package_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = manifest_path(package_dir)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def list_registered_real_cases(package_dir: Path) -> list[dict[str, Any]]:
    """Return registered case stubs from the package manifest."""
    manifest = load_package_manifest(package_dir)
    out = []
    for row in manifest.get("cases") or []:
        if isinstance(row, dict) and row.get("example_id"):
            out.append(dict(row))
    return out


def discover_real_case_dirs(package_dir: Path) -> list[Path]:
    """Discover real case directories from manifest + on-disk folders.

    Manifest is authoritative for registration order. Orphan directories with
    ``case_manifest.json`` are included and flagged so they can be registered.
    """
    root = real_samples_root(package_dir)
    if not root.is_dir():
        return []
    registered = []
    seen: set[str] = set()
    for row in list_registered_real_cases(package_dir):
        eid = str(row["example_id"])
        case_dir = case_dir_for(package_dir, eid)
        if case_dir.is_dir():
            registered.append(case_dir)
            seen.add(eid)
    orphans = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in seen:
            continue
        if (child / CASE_MANIFEST_NAME).is_file():
            orphans.append(child)
    return registered + orphans


def real_settings_digest(
    *,
    example_id: str,
    job_id: str,
    comparison_model: str = "original_versus_corrected",
) -> str:
    payload = {
        "case_kind": "real_job",
        "comparison_model": comparison_model,
        "example_id": example_id,
        "job_id": job_id,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def build_real_fingerprint(case_dir: Path, case_manifest: dict[str, Any]) -> dict[str, Any]:
    """Hash supplied real-job artifacts. Missing optionals bind as null."""
    live = _live_real_hashes(case_dir)
    return {
        "case_kind": "real_job",
        "comparison_model": "original_versus_corrected",
        "not_algorithm_v1_v2": True,
        **live,
        "settings_digest": real_settings_digest(
            example_id=str(case_manifest.get("example_id") or case_dir.name),
            job_id=str(case_manifest.get("job_id") or "unknown"),
        ),
        "musicxml_hash_normalized": True,
    }


def _live_real_hashes(case_dir: Path) -> dict[str, str | None]:
    live: dict[str, str | None] = {}
    for field, (filename, kind) in REAL_CORE_ARTIFACT_FILES.items():
        path = case_dir / filename
        if not path.is_file():
            live[field] = None
            continue
        if kind == "musicxml":
            live[field] = stable_musicxml_digest(path.read_text(encoding="utf-8"))
        else:
            live[field] = sha256_bytes(path.read_bytes())
    for field, (filename, kind) in REAL_OPTIONAL_ARTIFACT_FILES.items():
        if field == "audio_sha256":
            audio = _audio_path(case_dir)
            live[field] = sha256_bytes(audio.read_bytes()) if audio else None
            continue
        path = case_dir / filename
        if not path.is_file():
            live[field] = None
            continue
        if kind == "musicxml":
            live[field] = stable_musicxml_digest(path.read_text(encoding="utf-8"))
        else:
            live[field] = sha256_bytes(path.read_bytes())
    return live


def probe_real_case_artifacts(case_dir: Path) -> ArtifactProbe:
    """Recompute hashes for original/corrected real-job artifacts."""
    live = _live_real_hashes(case_dir)
    missing: list[str] = []
    unreadable: list[str] = []
    playback_available: dict[str, bool] = {}

    for field, (filename, _kind) in REAL_CORE_ARTIFACT_FILES.items():
        if live.get(field) is None:
            missing.append(filename)

    for field in (
        "original_score_midi_sha256",
        "corrected_musicxml_sha256",
        "corrected_score_midi_sha256",
        "input_midi_sha256",
        "corrections_sha256",
    ):
        filename = REAL_OPTIONAL_ARTIFACT_FILES[field][0]
        playback_available[field] = (case_dir / filename).is_file()

    audio = _audio_path(case_dir)
    playback_available["audio_sha256"] = audio is not None

    from evaluation.musical_baseline.reviews import load_recorded_fingerprint

    recorded_status, recorded, recorded_error = load_recorded_fingerprint(case_dir)
    changed: list[str] = []
    if recorded_status == "loaded" and isinstance(recorded, dict):
        for field in (
            "original_musicxml_sha256",
            "original_score_midi_sha256",
            "corrected_musicxml_sha256",
            "corrected_score_midi_sha256",
            "input_midi_sha256",
            "audio_sha256",
            "corrections_sha256",
        ):
            if recorded.get(field) != live.get(field):
                if field == "audio_sha256":
                    changed.append(audio.name if audio else "audio.*")
                elif field in REAL_CORE_ARTIFACT_FILES:
                    changed.append(REAL_CORE_ARTIFACT_FILES[field][0])
                else:
                    changed.append(REAL_OPTIONAL_ARTIFACT_FILES[field][0])

    core_present = live.get("original_musicxml_sha256") is not None and not unreadable
    artifacts_current = bool(
        core_present
        and recorded_status == "loaded"
        and not changed
        and not unreadable
        and not missing
    )
    return ArtifactProbe(
        live_hashes=live,
        recorded=recorded,
        recorded_status=recorded_status,
        recorded_error=recorded_error,
        missing_files=missing,
        unreadable_files=unreadable,
        changed_files=changed,
        playback_available=playback_available,
        core_present=core_present,
        artifacts_current=artifacts_current,
    )


def empty_real_review_template(
    *,
    example_id: str,
    composition_id: str,
    performance_id: str,
    fingerprint: dict[str, Any],
    acoustic_default: str = "not_reviewed",
) -> dict[str, Any]:
    """Blank review scaffold for a real job (original vs corrected)."""
    dims: dict[str, Any] = {}
    for name in REVIEW_DIMENSIONS:
        status = acoustic_default if name == "acoustic_accuracy" else "not_reviewed"
        # Acoustic stays not_reviewed until audio + reference labels exist.
        if name == "acoustic_accuracy" and acoustic_default == "not_applicable":
            status = "not_applicable"
        dims[name] = {
            "status": status,
            "versions": {"original": None, "corrected": None},
            "score": None,
            "notes": "",
            "comparison_model": "original_versus_corrected",
            "not_algorithm_v1_v2": True,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "example_id": example_id,
        "composition_id": composition_id,
        "performance_id": performance_id,
        "split": REAL_SAMPLES_DIRNAME,
        "case_kind": "real_job",
        "comparison_model": "original_versus_corrected",
        "not_algorithm_v1_v2": True,
        "attribution": {
            "reviewer": None,
            "role": None,
            "reviewed_at": None,
            "contact": None,
        },
        "artifact_binding": {
            key: fingerprint.get(key) for key in REAL_BINDING_FIELDS
        },
        "dimensions": dims,
        "citations": [],
        "correction_time": {
            "minutes": None,
            "kind": "unknown",
            "note": "Use kind=actual|estimated|unknown; do not invent.",
        },
        "musical_acceptance": "not_assessed",
        "invented_scores_forbidden": True,
        "human_owned": True,
    }


def validate_real_case_dir(case_dir: Path) -> ReviewValidation:
    """Validate a real-job case against live original/corrected artifacts."""
    case_manifest = load_case_manifest(case_dir)
    expected = {
        "example_id": str(case_manifest.get("example_id") or case_dir.name),
        "composition_id": str(
            case_manifest.get("composition_id") or f"real-comp-{case_dir.name}"
        ),
        "performance_id": str(
            case_manifest.get("performance_id")
            or f"real-perf-{case_manifest.get('job_id') or case_dir.name}"
        ),
        "split": REAL_SAMPLES_DIRNAME,
    }
    loaded = load_review(case_dir)
    probe = probe_real_case_artifacts(case_dir)
    current = None
    if probe.core_present and probe.recorded_status == "loaded" and probe.recorded:
        current = dict(probe.live_hashes)
        for key in REAL_METADATA_BINDING_FIELDS:
            current[key] = probe.recorded.get(key)
    return validate_review(
        loaded.data,
        expected=expected,
        fingerprint=current,
        load_status=loaded.status,
        load_error=loaded.error,
        artifact_probe=probe,
        binding_fields=REAL_BINDING_FIELDS,
        optional_null_fields=REAL_OPTIONAL_NULL_FIELDS,
        version_keys=("original", "corrected"),
    )


class RealImportConflict(RuntimeError):
    """Non-identical re-import rejected so registered evidence stays intact."""


# Files that define a registered case's evidence set (excluding generated meta).
TRACKED_CASE_ARTIFACTS = (
    "original.musicxml",
    "original.score.mid",
    "corrected.musicxml",
    "corrected.score.mid",
    "input.mid",
    CORRECTIONS_NAME,
    NOTE_INDEX_NAME,
    "reference_labels.json",
)


def _hash_case_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    name = path.name.lower()
    if name.endswith(".musicxml") or name.endswith(".xml"):
        return stable_musicxml_digest(path.read_text(encoding="utf-8"))
    return sha256_bytes(path.read_bytes())


def case_content_fingerprint(case_dir: Path) -> dict[str, str | None]:
    """Content hashes for every tracked evidence file (None = absent)."""
    out: dict[str, str | None] = {}
    for name in TRACKED_CASE_ARTIFACTS:
        out[name] = _hash_case_file(case_dir / name)
    audio = _audio_path(case_dir)
    out["audio"] = sha256_bytes(audio.read_bytes()) if audio else None
    return out


def _next_revision_example_id(package_dir: Path, base_id: str) -> str:
    """Allocate ``base-r2``, ``base-r3``, … without colliding on disk/manifest."""
    existing = {row.get("example_id") for row in list_registered_real_cases(package_dir)}
    root = real_samples_root(package_dir)
    if root.is_dir():
        existing.update(p.name for p in root.iterdir() if p.is_dir())
    n = 2
    while True:
        candidate = f"{base_id}-r{n}"
        if candidate not in existing and not case_dir_for(package_dir, candidate).exists():
            return candidate
        n += 1


def _populate_stage_from_bundle(
    bundle: Path, stage: Path, job_id: str
) -> dict[str, str | None]:
    """Copy bundle evidence into an empty staging directory (complete set only)."""
    copied: dict[str, str | None] = {}
    for dest_name, aliases in BUNDLE_ALIASES.items():
        src = _resolve_bundle_file(bundle, dest_name, aliases, job_id)
        if src is None:
            copied[dest_name] = None
            continue
        target = stage / dest_name
        shutil.copy2(src, target)
        copied[dest_name] = dest_name

    audio_src = None
    for name in AUDIO_CANDIDATES:
        candidate = bundle / name
        if candidate.is_file():
            audio_src = candidate
            break
    if audio_src is None and job_id:
        for ext in (".wav", ".mp3", ".flac", ".m4a"):
            candidate = bundle / f"{job_id}{ext}"
            if candidate.is_file():
                audio_src = candidate
                break
    if audio_src is not None:
        dest_audio = stage / f"audio{audio_src.suffix.lower()}"
        shutil.copy2(audio_src, dest_audio)
        copied["audio"] = dest_audio.name
    else:
        copied["audio"] = None

    refs = bundle / "reference_labels.json"
    if refs.is_file():
        shutil.copy2(refs, stage / "reference_labels.json")
        copied["reference_labels.json"] = "reference_labels.json"
    else:
        copied["reference_labels.json"] = None
    return copied


def _publish_stage_to_case(stage: Path, case_dir: Path) -> None:
    """Copy staged evidence into a new/empty case directory."""
    case_dir.mkdir(parents=True, exist_ok=True)
    for path in stage.iterdir():
        dest = case_dir / path.name
        if path.is_file():
            shutil.copy2(path, dest)
        elif path.is_dir():
            shutil.copytree(path, dest)


def _merge_engine_metadata(
    *,
    engine_commit: str | None,
    algorithm_version: str | None,
    provider: str | None,
    bundle: Path,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer explicit CLI values; else keep previous known metadata; else bundle."""
    engine = {
        "commit": engine_commit,
        "algorithm_version": algorithm_version,
        "provider": provider,
        "status": (
            "present"
            if any([engine_commit, algorithm_version, provider])
            else "unknown"
        ),
    }
    if engine["status"] == "unknown":
        engine_path = bundle / "engine.json"
        if engine_path.is_file():
            try:
                eng = json.loads(engine_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                eng = None
            if isinstance(eng, dict):
                engine = {
                    "commit": eng.get("commit") or eng.get("engine_commit"),
                    "algorithm_version": eng.get("algorithm_version"),
                    "provider": eng.get("provider"),
                    "status": "present",
                }
    if engine["status"] == "unknown" and isinstance(previous, dict):
        prev_engine = previous.get("engine")
        if isinstance(prev_engine, dict) and prev_engine.get("status") == "present":
            return dict(prev_engine)
    return engine


def import_real_job_bundle(
    bundle_dir: Path,
    *,
    package_dir: Path,
    job_id: str,
    example_id: str | None = None,
    engine_commit: str | None = None,
    algorithm_version: str | None = None,
    provider: str | None = None,
    permitted_use: str | None = None,
    title: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Import an already-downloaded job bundle into the review package.

    Registered originals are immutable. Identical re-imports are idempotent.
    A changed evidence set is rejected unless ``force=True``, which publishes a
    **new revision** (``example_id-rN``) and leaves the prior case + review
    binding untouched. Never overwrites an existing case directory in place.
    Stages the full import and validates before updating the package manifest.
    """
    import tempfile

    bundle = Path(bundle_dir)
    if not bundle.is_dir():
        raise FileNotFoundError(f"bundle directory not found: {bundle}")
    base_eid = (example_id or f"real-job-{job_id}").strip()
    if not base_eid:
        raise ValueError("example_id required")

    with tempfile.TemporaryDirectory(prefix="notascore-real-import-") as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        copied = _populate_stage_from_bundle(bundle, stage, job_id)
        if not (stage / "original.musicxml").is_file():
            raise FileNotFoundError(
                "bundle must include unedited MusicXML as original.musicxml "
                "(or unedited.musicxml / automatic.musicxml)"
            )
        staged_fp = case_content_fingerprint(stage)

        publish_eid = base_eid
        case_dir = case_dir_for(package_dir, publish_eid)
        previous_manifest: dict[str, Any] | None = None
        supersedes: str | None = None
        action = "created"

        if case_dir.is_dir() and any(case_dir.iterdir()):
            previous_manifest = load_case_manifest(case_dir)
            existing_fp = case_content_fingerprint(case_dir)
            if existing_fp == staged_fp:
                # Idempotent: do not rewrite artifacts or manifest bindings.
                fp_path = case_dir / FINGERPRINT_NAME
                fingerprint = (
                    json.loads(fp_path.read_text(encoding="utf-8"))
                    if fp_path.is_file()
                    else build_real_fingerprint(case_dir, previous_manifest or {})
                )
                return {
                    "example_id": publish_eid,
                    "job_id": job_id,
                    "case_dir": str(case_dir),
                    "manifest": str(manifest_path(package_dir)),
                    "fingerprint": fingerprint,
                    "case_manifest": previous_manifest,
                    "review_write": {"action": "unchanged_idempotent"},
                    "form_write": {"action": "unchanged_idempotent"},
                    "import_action": "idempotent",
                    "supersedes": None,
                }

            original_changed = (
                existing_fp.get("original.musicxml")
                != staged_fp.get("original.musicxml")
            )
            human = False
            if (case_dir / REVIEW_JSON_NAME).is_file():
                loaded = load_review(case_dir)
                human = bool(
                    loaded.status == "loaded"
                    and loaded.data
                    and review_has_human_input(loaded.data)
                )
            # Human input never bypasses overwrite protection.
            if not force:
                raise RealImportConflict(
                    f"Case {publish_eid!r} already registered with different "
                    f"artifacts (original_changed={original_changed}, "
                    f"human_review={human}). Refusing in-place overwrite. "
                    "Re-import the identical bundle for a no-op, or pass "
                    "force=True to publish a new revision "
                    f"({publish_eid}-rN) that preserves the old case."
                )
            # force → new revision; never erase the prior case.
            supersedes = publish_eid
            publish_eid = _next_revision_example_id(package_dir, base_eid)
            case_dir = case_dir_for(package_dir, publish_eid)
            action = "revision"
            previous_manifest = None  # new case; do not inherit unless below

        if case_dir.exists() and any(case_dir.iterdir()):
            raise RealImportConflict(
                f"Refusing to publish into non-empty case dir {case_dir}"
            )

        package_manifest_before = load_package_manifest(package_dir)
        published = False
        try:
            _publish_stage_to_case(stage, case_dir)
            published = True

            # Prefer explicit permitted_use; else keep prior known value when revising family.
            prior_for_meta = None
            if supersedes:
                prior_for_meta = load_case_manifest(
                    case_dir_for(package_dir, supersedes)
                )
            if permitted_use:
                permitted = {"status": "present", "value": permitted_use}
            elif isinstance(prior_for_meta, dict):
                prev_use = prior_for_meta.get("permitted_use")
                permitted = (
                    dict(prev_use)
                    if isinstance(prev_use, dict)
                    else {"status": "unknown", "value": None}
                )
            else:
                permitted = {"status": "unknown", "value": None}

            engine = _merge_engine_metadata(
                engine_commit=engine_commit,
                algorithm_version=algorithm_version,
                provider=provider,
                bundle=bundle,
                previous=prior_for_meta,
            )
            title_value = title
            if title_value is None and isinstance(prior_for_meta, dict):
                title_value = prior_for_meta.get("title")
            if not title_value:
                title_value = f"Real job {job_id}"
            if action == "revision":
                title_value = f"{title_value} (revision of {supersedes})"

            source_note_ids = _source_note_ids_status(case_dir)
            has_audio = _audio_path(case_dir) is not None
            has_refs = (case_dir / "reference_labels.json").is_file()
            acoustic_default = (
                "not_reviewed" if (has_audio and has_refs) else "not_applicable"
            )

            # Artifact presence comes only from this staged set — no leftovers.
            case_manifest = {
                "schema_version": SCHEMA_VERSION,
                "case_kind": "real_job",
                "example_id": publish_eid,
                "job_id": job_id,
                "composition_id": f"real-comp-{job_id}",
                "performance_id": f"real-perf-{job_id}",
                "split": REAL_SAMPLES_DIRNAME,
                "title": title_value,
                "comparison_model": "original_versus_corrected",
                "not_algorithm_v1_v2": True,
                "not_in_p1_synthetic_candidate_set": True,
                "engine": engine,
                "permitted_use": permitted,
                "audio": _status_token(has_audio, value=copied.get("audio")),
                "reference_labels": _status_token(has_refs),
                "source_note_ids": source_note_ids,
                "artifacts": {
                    "original_musicxml": "original.musicxml",
                    "original_score_midi": copied.get("original.score.mid"),
                    "corrected_musicxml": copied.get("corrected.musicxml"),
                    "corrected_score_midi": copied.get("corrected.score.mid"),
                    "input_midi": copied.get("input.mid"),
                    "corrections": copied.get(CORRECTIONS_NAME),
                    "note_index": copied.get(NOTE_INDEX_NAME),
                    "audio": copied.get("audio"),
                },
                "content_fingerprint": staged_fp,
                "supersedes": supersedes,
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "note": (
                    "Original vs corrected evidence for musician review. "
                    "Corrected exports are not algorithm v2. Registered "
                    "originals are immutable; force publishes a new revision. "
                    "Missing fields stay unknown/missing."
                ),
            }
            (case_dir / CASE_MANIFEST_NAME).write_text(
                json.dumps(case_manifest, indent=2) + "\n", encoding="utf-8"
            )

            fingerprint = build_real_fingerprint(case_dir, case_manifest)
            # Ensure fingerprint agrees with staged content fingerprint.
            if fingerprint.get("original_musicxml_sha256") != staged_fp.get(
                "original.musicxml"
            ):
                raise RealImportConflict(
                    "internal error: published original hash mismatch vs stage"
                )
            (case_dir / FINGERPRINT_NAME).write_text(
                json.dumps(fingerprint, indent=2) + "\n", encoding="utf-8"
            )

            template = empty_real_review_template(
                example_id=publish_eid,
                composition_id=case_manifest["composition_id"],
                performance_id=case_manifest["performance_id"],
                fingerprint=fingerprint,
                acoustic_default=acoustic_default,
            )
            review_write = write_review_if_absent(case_dir, template)
            form_md = _real_review_form_markdown(case_manifest)
            form_write = write_review_form_if_absent(case_dir, form_md)

            report = {
                **case_manifest,
                "artifact_fingerprint": fingerprint,
                "review": {"write": review_write, "form_write": form_write},
                "package_role": "real_job_review_case",
            }
            (case_dir / CASE_REPORT_NAME).write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )

            # Package manifest last — only after the case is fully written.
            package_manifest = load_package_manifest(package_dir)
            cases = [
                row
                for row in (package_manifest.get("cases") or [])
                if isinstance(row, dict) and row.get("example_id") != publish_eid
            ]
            cases.append(
                {
                    "example_id": publish_eid,
                    "job_id": job_id,
                    "registered_at": case_manifest["registered_at"],
                    "case_kind": "real_job",
                    "comparison_model": "original_versus_corrected",
                    "supersedes": supersedes,
                }
            )
            package_manifest["cases"] = cases
            package_manifest["schema_version"] = SCHEMA_VERSION
            save_package_manifest(package_dir, package_manifest)

            return {
                "example_id": publish_eid,
                "job_id": job_id,
                "case_dir": str(case_dir),
                "manifest": str(manifest_path(package_dir)),
                "fingerprint": fingerprint,
                "case_manifest": case_manifest,
                "review_write": review_write,
                "form_write": form_write,
                "import_action": action,
                "supersedes": supersedes,
            }
        except Exception:
            # Failed publish must not leave a partial new case or corrupt the
            # package manifest. Restore prior package manifest if we got that far.
            if published and case_dir.exists() and action in {"created", "revision"}:
                # Only delete the new target — never the superseded case.
                shutil.rmtree(case_dir, ignore_errors=True)
            save_package_manifest(package_dir, package_manifest_before)
            raise


def _copy_aliased(
    bundle: Path, dest: Path, dest_name: str, aliases: tuple[str, ...]
) -> Path | None:
    src = _find_first(bundle, aliases)
    if src is None:
        # Also accept job-id prefixed names if present as sole musicxml/midi.
        return None
    target = dest / dest_name
    if src.resolve() != target.resolve():
        shutil.copy2(src, target)
    return target


def _resolve_bundle_file(
    bundle: Path, dest_name: str, aliases: tuple[str, ...], job_id: str | None
) -> Path | None:
    found = _find_first(bundle, aliases)
    if found:
        return found
    if job_id:
        if dest_name == "original.musicxml":
            return _find_first(bundle, (f"{job_id}.musicxml", f"{job_id}.unedited.musicxml"))
        if dest_name == "original.score.mid":
            return _find_first(bundle, (f"{job_id}.score.mid", f"{job_id}.unedited.score.mid"))
        if dest_name == "input.mid":
            return _find_first(bundle, (f"{job_id}.raw.mid", f"{job_id}.mid"))
        if dest_name.startswith("audio"):
            return _find_first(bundle, (f"{job_id}.wav", f"{job_id}.mp3", f"{job_id}.flac"))
    return None


def load_case_manifest(case_dir: Path) -> dict[str, Any]:
    path = case_dir / CASE_MANIFEST_NAME
    if not path.is_file():
        return {
            "example_id": case_dir.name,
            "job_id": "unknown",
            "case_kind": "real_job",
            "split": REAL_SAMPLES_DIRNAME,
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be an object")
    return data


def _source_note_ids_status(case_dir: Path) -> dict[str, Any]:
    path = case_dir / NOTE_INDEX_NAME
    if not path.is_file():
        return {"status": "missing", "count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unreadable", "count": 0}
    notes = data.get("notes") if isinstance(data, dict) else None
    if not isinstance(notes, list):
        return {"status": "missing", "count": 0}
    ids = [
        n.get("source_note_id") or n.get("id")
        for n in notes
        if isinstance(n, dict)
    ]
    present = [i for i in ids if i]
    if not present:
        return {"status": "missing", "count": 0}
    return {"status": "present", "count": len(present)}


def _real_review_form_markdown(case_manifest: dict[str, Any]) -> str:
    eid = case_manifest.get("example_id")
    job_id = case_manifest.get("job_id")
    engine = case_manifest.get("engine") or {}
    return "\n".join(
        [
            f"# Review form — `{eid}` (real job)",
            "",
            f"- Job ID: `{job_id}`",
            f"- Title: {case_manifest.get('title')}",
            f"- Comparison: **original vs corrected** (not algorithm v1/v2)",
            f"- Engine commit: `{engine.get('commit')}` (status={engine.get('status')})",
            f"- Algorithm: `{engine.get('algorithm_version')}`",
            f"- Provider: `{engine.get('provider')}`",
            f"- Permitted use: `{case_manifest.get('permitted_use')}`",
            f"- Audio: `{case_manifest.get('audio')}`",
            f"- Source note IDs: `{case_manifest.get('source_note_ids')}`",
            f"- Reference labels: `{case_manifest.get('reference_labels')}`",
            "",
            "Fill `review.json` (authoritative). Copy hashes from",
            "`artifact_fingerprint.json` into `artifact_binding`.",
            "Set `correction_time.kind` to `actual`, `estimated`, or `unknown`.",
            "Cite measures/timestamps in `citations`.",
            "",
            "Acoustic accuracy requires audio **and** reference labels;",
            "otherwise leave `not_applicable`.",
            "",
        ]
    )


def real_case_row(case_dir: Path) -> dict[str, Any]:
    """Build a report row for a discovered real case (no fingerprint trust)."""
    manifest = load_case_manifest(case_dir)
    report_path = case_dir / CASE_REPORT_NAME
    row: dict[str, Any]
    if report_path.is_file():
        try:
            row = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            row = dict(manifest)
    else:
        row = dict(manifest)
    row.pop("artifact_fingerprint", None)
    row["example_id"] = str(manifest.get("example_id") or case_dir.name)
    row["composition_id"] = str(
        manifest.get("composition_id") or f"real-comp-{case_dir.name}"
    )
    row["performance_id"] = str(
        manifest.get("performance_id")
        or f"real-perf-{manifest.get('job_id') or case_dir.name}"
    )
    row["split"] = REAL_SAMPLES_DIRNAME
    row["case_kind"] = "real_job"
    row["comparison_model"] = "original_versus_corrected"
    row["not_algorithm_v1_v2"] = True
    row["not_in_p1_synthetic_candidate_set"] = True
    row["case_dir"] = str(case_dir)
    return row


def validate_and_summarize_real_cases(package_dir: Path) -> dict[str, Any]:
    """Discover, validate, and summarize registered real-job cases."""
    case_dirs = discover_real_case_dirs(package_dir)
    validations: list[ReviewValidation] = []
    rows: list[dict[str, Any]] = []
    for case_dir in case_dirs:
        row = real_case_row(case_dir)
        validation = validate_real_case_dir(case_dir)
        validations.append(validation)
        rows.append(
            {
                **row,
                "review": {
                    "validation": validation.to_dict(),
                    "review_complete": validation.review_complete,
                    "musically_accepted": validation.musically_accepted,
                    "binding_stale": validation.binding_stale,
                    "artifacts_stale": validation.artifacts_stale,
                },
            }
        )
    from evaluation.musical_baseline.reviews import aggregate_reviews

    summary = aggregate_reviews(validations)
    return {
        "count": len(rows),
        "cases": rows,
        "review_summary": summary,
        "musician_reviewed_complete": summary.get("review_complete_count", 0),
        "musically_accepted_count": summary.get("musically_accepted_count", 0),
        "stale_count": summary.get("stale_count", 0),
        "note": (
            "Real-sample reviews are tracked separately from the synthetic "
            "15-case P1 completion count."
        ),
    }
