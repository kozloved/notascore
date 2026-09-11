"""Shared live-smoke checks. Diagnostic only — does not change pipeline routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from modes import parse_transcription_mode

LIVE_PIPELINE = "live"
LIVE_ORCHESTRATOR = "nextgen"


class SmokeFailure(Exception):
    pass


def resolve_mode(value: str | None) -> str:
    raw = (value or "solo").strip() or "solo"
    try:
        return parse_transcription_mode(raw)
    except ValueError as exc:
        raise SmokeFailure(f"Unknown MODE={raw!r}. {exc}") from exc


def upload_form_fields(*, mode: str, audio_path: str) -> list[tuple[str, str]]:
    """Curl -F fields for a live smoke upload. Canonical mode only."""
    canonical = resolve_mode(mode)
    return [
        ("file", f"@{audio_path};type=audio/wav"),
        ("mode", canonical),
    ]


def mt3_available(health: dict[str, Any]) -> bool:
    modes = health.get("modes") or {}
    polyphonic = health.get("polyphonic") or {}
    return bool(modes.get("polyphonic") or polyphonic.get("available"))


def assert_health_cutover(health: dict[str, Any]) -> None:
    ng = health.get("nextgen") or {}
    errors = []
    if ng.get("pipeline_mode") != LIVE_PIPELINE:
        errors.append(f"pipeline_mode={ng.get('pipeline_mode')!r} (expected live)")
    if ng.get("orchestrator_active") is not True:
        errors.append(f"orchestrator_active={ng.get('orchestrator_active')!r} (expected true)")
    for key in (
        "separation_enabled",
        "stem_transcription_enabled",
        "fusion_enabled",
        "ensemble_render_enabled",
    ):
        if ng.get(key) is not False:
            errors.append(f"{key}={ng.get(key)!r} (expected false for first cutover)")
    if errors:
        raise SmokeFailure("health nextgen check failed:\n  " + "\n  ".join(errors))


def assert_polyphonic_backend(health: dict[str, Any]) -> None:
    if mt3_available(health):
        return
    raise SmokeFailure(
        "Cannot run polyphonic smoke:\nMT3 backend is not configured/available."
    )


def assert_job_mode(job: dict[str, Any], expected: str) -> None:
    got = job.get("mode")
    if got != expected:
        raise SmokeFailure(
            f"requested mode = {expected}\njob mode = {got}\n"
            "A polyphonic smoke test must not be processed as Solo."
        )


def assert_live_provenance(prov: dict[str, Any], *, mode: str) -> None:
    if prov.get("pipeline_mode") != LIVE_PIPELINE:
        raise SmokeFailure(f"provenance pipeline_mode={prov.get('pipeline_mode')!r}")
    if prov.get("orchestrator") != LIVE_ORCHESTRATOR:
        raise SmokeFailure(f"provenance orchestrator={prov.get('orchestrator')!r}")
    if mode != "polyphonic":
        return
    transcription = prov.get("transcription") or {}
    if transcription.get("backend") != "mt3":
        raise SmokeFailure(
            f"transcription.backend={transcription.get('backend')!r} (expected mt3)"
        )
    if transcription.get("raw_identity_match") is not True:
        raise SmokeFailure(
            f"raw_identity_match={transcription.get('raw_identity_match')!r}"
        )
    provider = transcription.get("provider_raw_sha256")
    saved = transcription.get("saved_raw_sha256")
    if not provider:
        raise SmokeFailure("provider_raw_sha256 is null")
    if provider != saved:
        raise SmokeFailure(
            f"provider_raw_sha256={provider} != saved_raw_sha256={saved}"
        )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def format_smoke_report(
    *,
    case: str,
    mode: str,
    health: dict[str, Any] | None,
    provenance: dict[str, Any],
    raw_sha: str,
    score_sha: str,
    artifacts: dict[str, bool],
    result: str,
) -> str:
    ng = (health or {}).get("nextgen") or {}
    transcription = provenance.get("transcription") or {}
    identity = transcription.get("raw_identity_match")
    if identity is True:
        identity_label = "PASS"
    elif identity is False:
        identity_label = "FAIL"
    else:
        identity_label = "n/a (solo has no provider MIDI bytes)"
    mt3_label = "available" if mt3_available(health or {}) else "unavailable"
    lines = [
        "NotaScore Next-Gen Production Smoke",
        "",
        f"case: {case or '(none)'}",
        f"mode: {mode}",
        "",
        f"pipeline: {provenance.get('pipeline_mode') or ng.get('pipeline_mode')}",
        f"orchestrator: {provenance.get('orchestrator')}",
        "",
        f"MT3: {mt3_label}",
        f"raw identity: {identity_label}",
        "",
        "raw sha:",
        f"  {raw_sha}",
        "",
        "score sha:",
        f"  {score_sha}",
        "",
        "artifacts:",
    ]
    for name in ("raw.mid", "score.mid", "musicxml", "manifest", "provenance", "tempo"):
        ok = artifacts.get(name, False)
        lines.append(f"  {name:<14} {'OK' if ok else 'MISSING'}")
    lines.extend(
        [
            "",
            "federation:",
            "  separation     OFF",
            "  stem AMT       OFF",
            "  fusion         OFF",
            "",
            f"RESULT: {result}",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_json_arg(raw: str) -> dict[str, Any]:
    if raw == "-":
        return json.load(sys.stdin)
    path = Path(raw)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(raw)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live production smoke helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mode = sub.add_parser("resolve-mode")
    p_mode.add_argument("mode")

    p_fields = sub.add_parser("upload-fields")
    p_fields.add_argument("mode")
    p_fields.add_argument("audio")

    p_health = sub.add_parser("check-health")
    p_health.add_argument("payload", nargs="?", default="-")
    p_health.add_argument("--mode", default="solo")

    p_job = sub.add_parser("check-job")
    p_job.add_argument("payload", nargs="?", default="-")
    p_job.add_argument("--mode", required=True)

    p_prov = sub.add_parser("check-provenance")
    p_prov.add_argument("payload", nargs="?", default="-")
    p_prov.add_argument("--mode", required=True)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "resolve-mode":
            print(resolve_mode(args.mode))
            return 0
        if args.cmd == "upload-fields":
            mode = resolve_mode(args.mode)
            for key, value in upload_form_fields(mode=mode, audio_path=args.audio):
                print(f"{key}={value}")
            return 0
        if args.cmd == "check-health":
            health = _load_json_arg(args.payload)
            assert_health_cutover(health)
            mode = resolve_mode(args.mode)
            if mode == "polyphonic":
                assert_polyphonic_backend(health)
            print("health nextgen: pipeline_mode=live orchestrator_active=true federation=off")
            if mode == "polyphonic":
                print("MT3: available")
            return 0
        if args.cmd == "check-job":
            job = _load_json_arg(args.payload)
            assert_job_mode(job, resolve_mode(args.mode))
            print(f"requested mode = {resolve_mode(args.mode)}")
            print(f"job mode = {job.get('mode')}")
            return 0
        if args.cmd == "check-provenance":
            prov = _load_json_arg(args.payload)
            assert_live_provenance(prov, mode=resolve_mode(args.mode))
            print("provenance: pipeline_mode=live orchestrator=nextgen")
            return 0
    except SmokeFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
