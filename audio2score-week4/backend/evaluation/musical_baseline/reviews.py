"""Human review schema, validation, artifact binding, and completion rules.

Human-owned files (`review.json`, filled `REVIEW_FORM.md`) are never silently
overwritten. Generated fingerprints and reports compare bindings by content
hash, not timestamps.

Completion is not musical acceptance: a complete review may rate fail.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.musical_baseline.catalog import REVIEW_DIMENSIONS
from mir.notation_settings import (
    ALGORITHM_VERSION_CURRENT,
    ALGORITHM_VERSION_READABLE,
)

SCHEMA_VERSION = 1

# Musician-facing statuses for rated dimensions.
HUMAN_RATING_STATUSES = frozenset(
    {"pass", "fail", "needs_work", "not_reviewed", "not_applicable"}
)
# Aliases accepted on load; normalized before counting.
STATUS_ALIASES = {
    "unreviewed": "not_reviewed",
    "passed": "pass",
    "failed": "fail",
    "ok": "pass",
}
# Statuses that count as a completed human rating for a required dimension.
COMPLETED_RATING_STATUSES = frozenset({"pass", "fail", "needs_work"})
# Required for P1 review-completion counts (not acoustic; not export alone).
REQUIRED_COMPLETION_DIMENSIONS = (
    "musical_interpretation_accuracy",
    "human_correction_effort",
)
PER_VERSION_KEYS = ("v1", "v2")
ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)

REVIEW_JSON_NAME = "review.json"
REVIEW_FORM_NAME = "REVIEW_FORM.md"
REVIEW_FORM_TEMPLATE_NAME = "REVIEW_FORM.template.md"
FINGERPRINT_NAME = "artifact_fingerprint.json"
CASE_REPORT_NAME = "case_report.json"

COMPLETION_CRITERIA = {
    "schema_version": SCHEMA_VERSION,
    "required_dimensions": list(REQUIRED_COMPLETION_DIMENSIONS),
    "completed_rating_statuses": sorted(COMPLETED_RATING_STATUSES),
    "not_counted_as_complete": sorted(
        HUMAN_RATING_STATUSES - COMPLETED_RATING_STATUSES
    )
    + ["unreviewed", "blocked", "automated_pending", "missing"],
    "attribution_required": ["reviewer", "reviewed_at"],
    "identity_fields": ["example_id", "composition_id", "performance_id", "split"],
    "binding_fields": [
        "midi_sha256",
        "v1_musicxml_sha256",
        "v2_musicxml_sha256",
        "v1_algorithm_version",
        "v2_algorithm_version",
        "settings_digest",
    ],
    "stale_rule": (
        "A review is stale when any recorded binding hash/setting differs from "
        "the current artifact fingerprint. Timestamps alone never invalidate."
    ),
    "musical_acceptance_rule": (
        "review_complete AND musical_interpretation_accuracy.status == 'pass'. "
        "fail/needs_work on interpretation yields review_complete but not accepted."
    ),
    "acoustic_note": (
        "Acoustic not_applicable or missing never counts toward P1 completion. "
        "Synthetic coverage does not prove acoustic accuracy."
    ),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


_VOLATILE_XML_ID = re.compile(
    r'\bid="(?:P|I)[0-9a-fA-F]{8,}"'
)


def stable_musicxml_digest(xml_text: str) -> str:
    """Hash MusicXML after stripping music21's non-deterministic part IDs."""
    normalized = _VOLATILE_XML_ID.sub('id="STABLE"', xml_text)
    # Collapse residual whitespace-only volatility without rewriting structure.
    return sha256_text(normalized)


def settings_digest(*, meter: str, tempo: float, example_id: str, source_id: str) -> str:
    payload = {
        "meter": str(meter),
        "tempo": float(tempo),
        "example_id": example_id,
        "source_id": source_id,
        "default_algorithm": ALGORITHM_VERSION_CURRENT,
        "opt_in_algorithm": ALGORITHM_VERSION_READABLE,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def build_fingerprint(
    *,
    midi_sha256: str,
    v1_musicxml: str,
    v2_musicxml: str,
    meter: str,
    tempo: float,
    example_id: str,
    source_id: str,
    v1_score_midi: bytes | None = None,
    v2_score_midi: bytes | None = None,
) -> dict[str, Any]:
    return {
        "midi_sha256": midi_sha256,
        "v1_musicxml_sha256": stable_musicxml_digest(v1_musicxml),
        "v2_musicxml_sha256": stable_musicxml_digest(v2_musicxml),
        "v1_score_midi_sha256": (
            sha256_bytes(v1_score_midi) if v1_score_midi else None
        ),
        "v2_score_midi_sha256": (
            sha256_bytes(v2_score_midi) if v2_score_midi else None
        ),
        "v1_algorithm_version": ALGORITHM_VERSION_CURRENT,
        "v2_algorithm_version": ALGORITHM_VERSION_READABLE,
        "settings_digest": settings_digest(
            meter=meter, tempo=tempo, example_id=example_id, source_id=source_id
        ),
        "meter": str(meter),
        "tempo": float(tempo),
        "musicxml_hash_normalized": True,
    }


def fingerprint_from_case_dir(case_dir: Path) -> dict[str, Any] | None:
    path = case_dir / FINGERPRINT_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def empty_review_template(
    *,
    example_id: str,
    composition_id: str,
    performance_id: str,
    split: str,
    fingerprint: dict[str, Any],
    acoustic_default: str = "not_applicable",
) -> dict[str, Any]:
    """Blank human-owned review scaffold. Not a completed review."""
    dims: dict[str, Any] = {}
    for name in REVIEW_DIMENSIONS:
        status = acoustic_default if name == "acoustic_accuracy" else "not_reviewed"
        dims[name] = {
            "status": status,
            "versions": {"v1": None, "v2": None},
            "score": None,
            "notes": "",
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "example_id": example_id,
        "composition_id": composition_id,
        "performance_id": performance_id,
        "split": split,
        "attribution": {
            "reviewer": None,
            "role": None,
            "reviewed_at": None,
            "contact": None,
        },
        "artifact_binding": {
            key: fingerprint.get(key)
            for key in COMPLETION_CRITERIA["binding_fields"]
        },
        "dimensions": dims,
        "musical_acceptance": "not_assessed",
        "invented_scores_forbidden": True,
        "human_owned": True,
    }


def _normalize_status(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    text = STATUS_ALIASES.get(text, text)
    return text


def _parse_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not ISO_DATE_RE.match(text):
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        if "T" in normalized or " " in normalized:
            datetime.fromisoformat(normalized.replace(" ", "T", 1))
        else:
            datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return text


@dataclass
class ReviewLoadResult:
    status: str  # missing | malformed | loaded
    path: Path
    data: dict[str, Any] | None = None
    error: str | None = None
    preserved: bool = True


def load_review(case_dir: Path) -> ReviewLoadResult:
    path = case_dir / REVIEW_JSON_NAME
    if not path.is_file():
        return ReviewLoadResult(status="missing", path=path, preserved=True)
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError) as exc:
        return ReviewLoadResult(
            status="malformed",
            path=path,
            error=f"{type(exc).__name__}: {exc}",
            preserved=True,
        )
    except json.JSONDecodeError as exc:
        return ReviewLoadResult(
            status="malformed",
            path=path,
            error=f"JSONDecodeError: {exc}",
            preserved=True,
        )
    if not isinstance(data, dict):
        return ReviewLoadResult(
            status="malformed",
            path=path,
            error="review.json root must be an object",
            preserved=True,
        )
    return ReviewLoadResult(status="loaded", path=path, data=data, preserved=True)


def review_has_human_input(data: dict[str, Any]) -> bool:
    """True when the file looks human-touched (preserve even if invalid).

    Legacy empty scaffolds embedded mechanical ``export_integrity`` with
    status ``passed``; that alone must not block template refresh.
    """
    attr = data.get("attribution") or {}
    if isinstance(attr, dict) and any(
        str(attr.get(k) or "").strip()
        for k in ("reviewer", "role", "reviewed_at", "contact")
    ):
        return True
    dims = data.get("dimensions") or {}
    if not isinstance(dims, dict):
        return True
    for name, dim in dims.items():
        if not isinstance(dim, dict):
            return True
        # Mechanical export rows from older scaffolds are not human input.
        if name == "export_integrity" and (
            dim.get("mechanical")
            or dim.get("reviewer") in {
                "automated_export_integrity",
                "automated_stage_gate",
            }
        ):
            continue
        status = _normalize_status(dim.get("status"))
        if status in COMPLETED_RATING_STATUSES:
            return True
        if str(dim.get("notes") or "").strip():
            return True
        if dim.get("score") is not None:
            return True
        versions = dim.get("versions") or {}
        if isinstance(versions, dict) and any(
            versions.get(v) for v in PER_VERSION_KEYS
        ):
            return True
    if data.get("musical_acceptance") not in (None, "not_assessed", ""):
        return True
    return False


@dataclass
class ReviewValidation:
    example_id: str
    load_status: str
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    identity_ok: bool = False
    attribution_ok: bool = False
    binding_current: bool = False
    binding_stale: bool = False
    binding_missing: bool = False
    dimensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    review_complete: bool = False
    musically_accepted: bool = False
    reviewer: str | None = None
    reviewed_at: str | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "load_status": self.load_status,
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "identity_ok": self.identity_ok,
            "attribution_ok": self.attribution_ok,
            "binding_current": self.binding_current,
            "binding_stale": self.binding_stale,
            "binding_missing": self.binding_missing,
            "dimensions": self.dimensions,
            "review_complete": self.review_complete,
            "musically_accepted": self.musically_accepted,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "completion_criteria": COMPLETION_CRITERIA,
        }


def validate_review(
    data: dict[str, Any] | None,
    *,
    expected: dict[str, str],
    fingerprint: dict[str, Any] | None,
    load_status: str = "loaded",
    load_error: str | None = None,
) -> ReviewValidation:
    example_id = expected.get("example_id") or ""
    result = ReviewValidation(
        example_id=example_id, load_status=load_status, valid=False
    )
    if load_status == "missing":
        result.errors.append("review.json missing")
        return result
    if load_status == "malformed":
        result.errors.append(load_error or "review.json malformed")
        return result
    if not isinstance(data, dict):
        result.errors.append("review payload is not an object")
        return result
    result.raw = data

    identity_ok = True
    for key in COMPLETION_CRITERIA["identity_fields"]:
        got = data.get(key)
        want = expected.get(key)
        if got != want:
            identity_ok = False
            result.errors.append(
                f"identity mismatch: {key}={got!r} expected {want!r}"
            )
    result.identity_ok = identity_ok

    attr = data.get("attribution")
    if not isinstance(attr, dict):
        result.errors.append("attribution must be an object")
        attr = {}
    reviewer = str(attr.get("reviewer") or "").strip() or None
    reviewed_at = _parse_iso_date(attr.get("reviewed_at"))
    result.reviewer = reviewer
    result.reviewed_at = reviewed_at
    if not reviewer:
        result.errors.append("attribution.reviewer required for a completed review")
    if attr.get("reviewed_at") and reviewed_at is None:
        result.errors.append(
            "attribution.reviewed_at must be an ISO date or datetime"
        )
    if not reviewed_at:
        result.errors.append(
            "attribution.reviewed_at required for a completed review"
        )
    result.attribution_ok = bool(reviewer and reviewed_at)

    binding = data.get("artifact_binding")
    if not isinstance(binding, dict):
        result.binding_missing = True
        result.errors.append("artifact_binding missing or not an object")
        binding = {}
    elif fingerprint is None:
        result.warnings.append(
            "no current fingerprint available for binding check"
        )
        result.binding_missing = True
    else:
        missing_keys: list[str] = []
        stale_keys: list[str] = []
        for key in COMPLETION_CRITERIA["binding_fields"]:
            got = binding.get(key)
            want = fingerprint.get(key)
            if got in (None, ""):
                missing_keys.append(key)
            elif want is not None and got != want:
                stale_keys.append(key)
        if stale_keys:
            result.binding_stale = True
            result.errors.append(
                "artifact_binding stale vs current fingerprint: "
                + ", ".join(stale_keys)
            )
        elif missing_keys:
            result.binding_missing = True
            result.errors.append(
                "artifact_binding incomplete: " + ", ".join(missing_keys)
            )
        else:
            result.binding_current = True

    dims_in = data.get("dimensions")
    if not isinstance(dims_in, dict):
        result.errors.append("dimensions must be an object")
        dims_in = {}

    parsed_dims: dict[str, dict[str, Any]] = {}
    for name in REVIEW_DIMENSIONS:
        dim = dims_in.get(name)
        if not isinstance(dim, dict):
            result.errors.append(f"dimensions.{name} missing or not an object")
            parsed_dims[name] = {
                "status": "not_reviewed",
                "versions": {"v1": None, "v2": None},
                "score": None,
                "notes": "",
                "valid": False,
                "counts_as_rated": False,
            }
            continue
        status = _normalize_status(dim.get("status"))
        if status is None:
            status = "not_reviewed"
        status_valid = status in HUMAN_RATING_STATUSES
        if not status_valid:
            result.errors.append(
                f"dimensions.{name}.status invalid: {dim.get('status')!r}"
            )
        versions = dim.get("versions") or {}
        if versions is None:
            versions = {}
        if not isinstance(versions, dict):
            result.errors.append(f"dimensions.{name}.versions must be an object")
            versions = {}
            status_valid = False
        version_vals: dict[str, str | None] = {}
        for key in PER_VERSION_KEYS:
            raw_v = versions.get(key)
            if raw_v in (None, ""):
                version_vals[key] = None
                continue
            nv = _normalize_status(raw_v)
            if nv not in HUMAN_RATING_STATUSES:
                result.errors.append(
                    f"dimensions.{name}.versions.{key} invalid: {raw_v!r}"
                )
                status_valid = False
                version_vals[key] = None
            else:
                version_vals[key] = nv
        score: Any = dim.get("score")
        if score is not None:
            try:
                score_num = float(score)
            except (TypeError, ValueError):
                result.errors.append(
                    f"dimensions.{name}.score must be numeric or null"
                )
                score = None
                status_valid = False
            else:
                if not (1.0 <= score_num <= 5.0):
                    result.errors.append(
                        f"dimensions.{name}.score must be in 1..5 when set"
                    )
                    status_valid = False
                score = score_num
        parsed_dims[name] = {
            "status": status if status_valid else "not_reviewed",
            "versions": version_vals,
            "score": score,
            "notes": str(dim.get("notes") or ""),
            "valid": status_valid,
            "counts_as_rated": status in COMPLETED_RATING_STATUSES and status_valid,
        }
    result.dimensions = parsed_dims

    hard_errors = [
        e
        for e in result.errors
        if (
            "invalid" in e
            or "mismatch" in e
            or "must be" in e
            or "malformed" in e.lower()
            or e.endswith("not an object")
            or "missing or not an object" in e
        )
    ]
    result.valid = (
        not hard_errors and result.identity_ok and load_status == "loaded"
    )

    required_ok = all(
        (parsed_dims.get(name) or {}).get("counts_as_rated")
        for name in REQUIRED_COMPLETION_DIMENSIONS
    )
    result.review_complete = bool(
        result.valid
        and result.identity_ok
        and result.attribution_ok
        and result.binding_current
        and not result.binding_stale
        and required_ok
    )
    interp = (parsed_dims.get("musical_interpretation_accuracy") or {}).get(
        "status"
    )
    result.musically_accepted = bool(
        result.review_complete and interp == "pass"
    )
    return result


def validate_case_dir(
    case_dir: Path,
    *,
    expected: dict[str, str],
    fingerprint: dict[str, Any] | None = None,
) -> ReviewValidation:
    loaded = load_review(case_dir)
    fp = (
        fingerprint
        if fingerprint is not None
        else fingerprint_from_case_dir(case_dir)
    )
    return validate_review(
        loaded.data,
        expected=expected,
        fingerprint=fp,
        load_status=loaded.status,
        load_error=loaded.error,
    )


def write_review_if_absent(
    case_dir: Path,
    template: dict[str, Any],
) -> dict[str, Any]:
    """Create or safely refresh ``review.json``.

    - Missing → write template.
    - Malformed → preserve bytes; never reset.
    - Human-touched (rated/attributed/notes) → preserve entirely.
    - Blank scaffold with no human input → refresh binding/identity template.
    """
    path = case_dir / REVIEW_JSON_NAME
    if not path.exists():
        path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
        return {
            "action": "created_template",
            "load_status": "created",
            "path": str(path),
        }
    loaded = load_review(case_dir)
    if loaded.status == "malformed":
        return {
            "action": "preserved_malformed",
            "load_status": loaded.status,
            "error": loaded.error,
            "path": str(path),
        }
    if loaded.status == "loaded" and loaded.data is not None:
        if review_has_human_input(loaded.data):
            return {
                "action": "preserved_human",
                "load_status": loaded.status,
                "path": str(path),
            }
        # Empty scaffold: refresh so artifact_binding matches current package.
        path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
        return {
            "action": "refreshed_empty_template",
            "load_status": "refreshed",
            "path": str(path),
        }
    return {
        "action": "preserved",
        "load_status": loaded.status,
        "error": loaded.error,
        "path": str(path),
    }


def write_review_form_if_absent(case_dir: Path, markdown: str) -> dict[str, Any]:
    path = case_dir / REVIEW_FORM_NAME
    template_path = case_dir / REVIEW_FORM_TEMPLATE_NAME
    template_path.write_text(markdown, encoding="utf-8")
    if path.exists():
        return {
            "action": "preserved",
            "path": str(path),
            "template": str(template_path),
        }
    path.write_text(markdown, encoding="utf-8")
    return {
        "action": "created",
        "path": str(path),
        "template": str(template_path),
    }


def aggregate_reviews(validations: list[ReviewValidation]) -> dict[str, Any]:
    complete = [v for v in validations if v.review_complete]
    accepted = [v for v in validations if v.musically_accepted]
    failing_complete = [v for v in complete if not v.musically_accepted]
    stale = [v for v in validations if v.binding_stale]
    malformed = [v for v in validations if v.load_status == "malformed"]
    invalid = [
        v
        for v in validations
        if v.load_status == "loaded" and not v.valid
    ]
    partial = [
        v
        for v in validations
        if v.load_status == "loaded"
        and v.valid
        and not v.review_complete
        and not v.binding_stale
    ]
    return {
        "criteria": COMPLETION_CRITERIA,
        "case_count": len(validations),
        "review_complete_count": len(complete),
        "musically_accepted_count": len(accepted),
        "reviewed_but_not_accepted_count": len(failing_complete),
        "stale_count": len(stale),
        "malformed_count": len(malformed),
        "invalid_count": len(invalid),
        "partial_count": len(partial),
        "complete_example_ids": [v.example_id for v in complete],
        "accepted_example_ids": [v.example_id for v in accepted],
        "reviewed_but_not_accepted_ids": [v.example_id for v in failing_complete],
        "stale_example_ids": [v.example_id for v in stale],
        "malformed_example_ids": [v.example_id for v in malformed],
        "note": (
            "review_complete_count is not musical acceptance and is not "
            "production readiness. Acoustic accuracy is tracked separately."
        ),
    }
