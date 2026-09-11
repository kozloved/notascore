"""Job sidecar filenames. No extra DB columns — files + ArtifactManifest."""

from __future__ import annotations

from pathlib import Path

CORE_SIDECARS = (
    ("raw.mid", "audio/midi"),
    ("validated.mid", "audio/midi"),
    ("score.mid", "audio/midi"),
    ("fused.mid", "audio/midi"),
    ("musicxml", "application/vnd.recordare.musicxml+xml"),
    ("tempo.json", "application/json"),
    ("performance.json", "application/json"),
    ("fused.json", "application/json"),
    ("fusion.json", "application/json"),
    ("provenance.json", "application/json"),
    ("manifest.json", "application/json"),
    ("debug.json", "application/json"),
    ("interpretation.json", "application/json"),
)


def job_work_dir(source: str | Path, job_id: str) -> Path:
    return Path(source).parent / f"bp_{job_id}"


def extra_result_files(out_dir: str | Path, job_id: str) -> list[Path]:
    """Sidecars to upload besides MusicXML / raw / validated / score MIDI."""
    root = Path(out_dir)
    names = (
        f"{job_id}.fused.mid",
        f"{job_id}.fused.json",
        f"{job_id}.fusion.json",
        f"{job_id}.manifest.json",
        f"{job_id}.provenance.json",
        f"{job_id}.tempo.json",
        f"{job_id}.performance.json",
        f"{job_id}.debug.json",
        f"{job_id}.interpretation.json",
    )
    found = [root / name for name in names if (root / name).exists()]
    found.extend(sorted(p for p in root.glob(f"{job_id}.stem.*") if p.is_file()))
    found.extend(sorted(p for p in root.glob(f"{job_id}.raw.*.mid") if p.is_file()))
    return found


def list_job_sidecars(result_storage_key: str, job_id: str) -> list[dict]:
    """Discover completed artifacts next to the stored MusicXML result."""
    result = Path(result_storage_key)
    folder = result.parent
    rows: list[dict] = []
    for suffix, content_type in CORE_SIDECARS:
        path = folder / f"{job_id}.{suffix}"
        if path.exists():
            rows.append(
                {
                    "name": path.name,
                    "kind": suffix,
                    "content_type": content_type,
                    "bytes": path.stat().st_size,
                }
            )
    for path in sorted(folder.glob(f"{job_id}.stem.*")):
        rows.append(
            {
                "name": path.name,
                "kind": "stem",
                "content_type": "audio/wav" if path.suffix.lower() == ".wav" else "application/octet-stream",
                "bytes": path.stat().st_size,
                "stem_id": path.name.split(".stem.", 1)[-1].rsplit(".", 1)[0],
            }
        )
    for path in sorted(folder.glob(f"{job_id}.raw.*.mid")):
        rows.append(
            {
                "name": path.name,
                "kind": "stem_midi",
                "content_type": "audio/midi",
                "bytes": path.stat().st_size,
                "stem_id": path.name[len(job_id) + 5 : -4],  # after '{id}.raw.'
            }
        )
    return rows


def sidecar_path(result_storage_key: str, job_id: str, filename: str) -> Path | None:
    name = Path(filename).name
    if not name.startswith(job_id):
        name = f"{job_id}.{name}" if not name.startswith(f"{job_id}.") else name
    path = Path(result_storage_key).parent / name
    if path.exists() and path.is_file():
        return path
    return None
