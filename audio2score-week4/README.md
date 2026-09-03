# NotaScore

NotaScore AI turns uploaded audio into editable MusicXML via the NotaScore Transcription Engine.

## Production deploy

- **Cheap VPS + Cloudflare Tunnel (recommended):** [deploy/VPS.md](deploy/VPS.md) — ~$5–6/month for frontend + API + Redis + Solo worker.
- **Split hosting overview:** [deploy/SPLIT_HOSTING.md](deploy/SPLIT_HOSTING.md) — Polyphonic GPU stays on Vast.ai.

## What is included?

- Redis Queue worker
- Storage abstraction
- Solo (Basic Pitch) and Polyphonic (YourMT3) transcription
- Per-job Solo / Polyphonic toggle on upload (`fast`/`quality` still accepted)
- Dummy MT3 MIDI command + HTTP contract scripts
- Real YourMT3 GPU worker (`gpu-worker/`, mt3-infer 0.2.0) for Polyphonic mode
- Worker that calls the transcription engine
- Frontend that shows engine info

## Project Structure

```text
audio2score-week4/
  backend/
    main.py
    database.py
    storage.py
    job_queue.py
    tasks.py
    worker.py
    transcription.py
    requirements.txt
    .env.example
    scripts/
      example_mt3.py
    uploads/
      .gitignore
    results/
      .gitignore
    .tmp/
      .gitignore
  frontend/
    app/
      layout.jsx
      page.jsx
    package.json
    .env.local.example
```

## Start Redis

Using Docker:

```bash
docker run -d --name audio2score-redis -p 6379:6379 redis:7
```

## Run Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

## Run Worker

In a second terminal:

```bash
cd backend
source .venv/bin/activate
python worker.py
```

## Run Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

## Transcription modes

Jobs choose **Solo** or **Polyphonic** at upload (`mode=solo|polyphonic`). Legacy `fast`/`quality` still work. MIDI files skip note detection and ignore the mode.

### Solo (default)

Basic Pitch on this machine. Same cleaner → CMR → grand-staff path as before.

### Polyphonic (YourMT3)

Polyphonic never falls back to Solo. The backend `MT3Backend` calls a remote GPU and expects **MIDI**. The rest of the job pipeline is unchanged.

**RunPod Serverless** (JSON `input.audio_base64` → `midi_base64`):

```env
MT3_ENDPOINT=https://api.runpod.ai/v2/g40wir5ey71e3/runsync
MT3_API_KEY=<RunPod API key>
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

`MT3_API_KEY` stays on the API / worker only. Do not put it in the frontend or commit it.

A URL without `/runsync` is normalized to `/runsync`. Manual check (same adapter as production jobs):

```text
cd audio2score-week4/backend
python scripts/run_runpod_mt3.py path/to/clip.wav
```

**Legacy HTTP worker** (multipart `file` → MIDI bytes or `{"midi_base64":"..."}`):

```env
MT3_ENDPOINT=http://127.0.0.1:8090/transcribe
MT3_API_KEY=
```

Alternatively a local command that writes MIDI to `{output}`:

```env
MT3_TRANSCRIBE_COMMAND=python scripts/example_mt3.py {input} {output}
MT3_TIMEOUT_SECONDS=300
```

Dummy helpers:

```text
backend/scripts/example_mt3.py
backend/scripts/example_mt3_http.py
backend/scripts/run_runpod_mt3.py
```

`GET /health` includes `modes.polyphonic`, `polyphonic.provider` (`runpod` | `http` | `command` | `none`), and the legacy alias `quality.available`. It never includes `MT3_API_KEY`. The UI greys out Polyphonic until a worker is configured.

Vast.ai / local GPU HTTP worker: [gpu-worker/README.md](gpu-worker/README.md) and [deploy/SPLIT_HOSTING.md](deploy/SPLIT_HOSTING.md).
