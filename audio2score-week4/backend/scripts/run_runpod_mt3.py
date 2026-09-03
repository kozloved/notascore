"""Manual / integration: audio → MT3Backend → RunPod YourMT3 → NoteEvents.

Uses the same MT3Backend.transcribe_notes() path as Polyphonic jobs.
Does not print MT3_API_KEY, audio base64, or MIDI base64.

  cd audio2score-week4/backend
  MT3_ENDPOINT=https://api.runpod.ai/v2/g40wir5ey71e3/runsync \\
  MT3_API_KEY=... \\
  python scripts/run_runpod_mt3.py path/to/clip.wav

If no audio path is given, writes a 2-second sine tone and uses that.

Optional --upload posts the file to POST /upload?mode=polyphonic on a running
API (default http://127.0.0.1:8000) so the real job queue is exercised. The
API and RQ worker must already have the same MT3_* environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _require_env() -> None:
    endpoint = (os.getenv("MT3_ENDPOINT") or "").strip()
    api_key = (os.getenv("MT3_API_KEY") or "").strip()
    if not endpoint:
        print("Set MT3_ENDPOINT to the RunPod /runsync URL.", file=sys.stderr)
        sys.exit(2)
    if not api_key:
        print("Set MT3_API_KEY (RunPod API key). Do not commit it.", file=sys.stderr)
        sys.exit(2)
    print(f"[run_runpod_mt3] endpoint={endpoint}")
    print("[run_runpod_mt3] api_key=configured")


def _write_tone(path: Path) -> Path:
    import numpy as np
    import soundfile as sf

    sr = 22050
    seconds = 2.0
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    tone = 0.2 * np.sin(2 * np.pi * 440 * t)
    sf.write(str(path), tone, sr)
    return path


def _transcribe_direct(audio_path: Path) -> None:
    from adapters.mt3_backend import MT3Backend, mt3_status

    status = mt3_status()
    print(f"[run_runpod_mt3] provider={status['provider']}")
    print(f"[run_runpod_mt3] audio={audio_path} bytes={audio_path.stat().st_size}")
    started = time.perf_counter()
    notes = MT3Backend().transcribe_notes(audio_path)
    elapsed = time.perf_counter() - started
    print(f"[run_runpod_mt3] notes={len(notes)}")
    print(f"[run_runpod_mt3] backend_seconds={elapsed:.2f}")
    print("[run_runpod_mt3] status=ok")


def _upload_and_wait(audio_path: Path, api_url: str, timeout: int) -> None:
    import urllib.error
    import urllib.request

    boundary = "notascore-runpod-manual"
    filename = audio_path.name
    payload = audio_path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + payload + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="mode"\r\n\r\n'
        f"polyphonic"
        f"\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        job = json.loads(response.read().decode("utf-8"))
    job_id = job.get("job_id") or job.get("id")
    print(f"[run_runpod_mt3] uploaded job_id={job_id} mode={job.get('mode')}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(
            f"{api_url.rstrip('/')}/jobs/{job_id}", timeout=30
        ) as response:
            state = json.loads(response.read().decode("utf-8"))
        status = state.get("status")
        print(f"[run_runpod_mt3] job status={status} progress={state.get('progress')}")
        if status == "completed":
            print(
                f"[run_runpod_mt3] job_seconds={time.perf_counter() - started:.2f}"
            )
            print("[run_runpod_mt3] status=ok")
            return
        if status == "failed":
            print(f"[run_runpod_mt3] job error={state.get('error')}", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
    raise TimeoutError(f"job {job_id} did not finish within {timeout}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="RunPod YourMT3 via MT3Backend")
    parser.add_argument("audio", nargs="?", help="Audio file (wav/mp3/m4a/flac)")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="POST /upload mode=polyphonic on a running API instead of calling the adapter directly",
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    _require_env()

    if args.audio:
        audio_path = Path(args.audio)
        if not audio_path.exists():
            print(f"Audio file not found: {audio_path}", file=sys.stderr)
            sys.exit(1)
    else:
        audio_path = Path("/tmp/notascore-runpod-tone.wav")
        _write_tone(audio_path)
        print(f"[run_runpod_mt3] wrote_tone={audio_path}")

    if args.upload:
        _upload_and_wait(audio_path, args.api_url, args.timeout)
        return
    _transcribe_direct(audio_path)


if __name__ == "__main__":
    main()
