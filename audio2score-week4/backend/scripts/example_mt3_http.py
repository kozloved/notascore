"""Dummy Quality/MT3 HTTP worker — documents the GPU MIDI contract.

A real MR-MT3 box should expose the same API and run Magenta MT3 on GPU.

  POST /transcribe
    multipart field `file` = audio (wav/mp3/m4a/flac)
    optional Authorization: Bearer <MT3_API_KEY>
  200 audio/midi  (MIDI bytes)
  or 200 application/json  {"midi_base64": "<base64 MIDI>"}

Point the API at this process:

  MT3_ENDPOINT=http://127.0.0.1:8090/transcribe

Usage:
  python scripts/example_mt3_http.py [--port 8090]
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from example_mt3 import write_dummy_midi  # noqa: E402

import tempfile


def _dummy_midi_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mt3.mid"
        write_dummy_midi(path, "http")
        return path.read_bytes()


class MT3ContractHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        if self.path.split("?", 1)[0].rstrip("/") != "/transcribe":
            self.send_error(404, "Use POST /transcribe")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = _dummy_midi_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "audio/midi")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Dummy MT3 HTTP worker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MT3ContractHandler)
    print(f"Dummy MT3 worker on http://{args.host}:{args.port}/transcribe")
    server.serve_forever()


if __name__ == "__main__":
    main()
