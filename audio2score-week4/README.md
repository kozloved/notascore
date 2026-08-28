# NotaScore

NotaScore AI turns uploaded audio into editable MusicXML via the NotaScore Transcription Engine.

## Production deploy (local + Cloudflare Tunnel)

See [deploy/README.md](deploy/README.md) for Docker Compose on a local machine with Cloudflare Tunnel for `notascore.com`.

## What is new in Week 4?

See [deploy/README.md](deploy/README.md) for Docker Compose + Nginx + Let's Encrypt on Always Free.

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

Polyphonic never falls back to Solo. Configure a GPU worker **or** a command that writes **MIDI** (not MusicXML):

```env
MT3_ENDPOINT=http://127.0.0.1:8090/transcribe
MT3_API_KEY=
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

The worker must accept `POST` with multipart field `file` and respond with MIDI bytes (`audio/midi`) or JSON `{"midi_base64":"..."}`.

Alternatively:

```env
MT3_TRANSCRIBE_COMMAND=python scripts/example_mt3.py {input} {output}
MT3_TIMEOUT_SECONDS=300
```

`{output}` is a `.mid` path. Dummy helpers:

```text
backend/scripts/example_mt3.py
backend/scripts/example_mt3_http.py
```

`GET /health` includes `modes.polyphonic` (and the legacy alias `quality.available`). The UI greys out Polyphonic until a worker is configured.

To run **real** YourMT3, put `gpu-worker/` on a Vast.ai GPU (12 GB+) and set `MT3_ENDPOINT` to its `/transcribe` URL. See [gpu-worker/README.md](gpu-worker/README.md) and [deploy/SPLIT_HOSTING.md](deploy/SPLIT_HOSTING.md).
