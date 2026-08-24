# NotaScore

NotaScore AI turns uploaded audio into editable MusicXML via the NotaScore Transcription Engine.

## Production deploy (local + Cloudflare Tunnel)

See [deploy/README.md](deploy/README.md) for Docker Compose on a local machine with Cloudflare Tunnel for `notascore.com`.

## What is new in Week 4?

See [deploy/README.md](deploy/README.md) for Docker Compose + Nginx + Let's Encrypt on Always Free.

## What is included?

- Redis Queue worker
- Storage abstraction
- Fast (Basic Pitch) and Quality (MR-MT3) transcription
- Per-job Fast / Quality toggle on upload
- Dummy MT3 MIDI command + HTTP contract scripts
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

Jobs choose **Fast** or **Quality** at upload (`mode=fast|quality`). MIDI files skip note detection and ignore the mode.

### Fast (default)

Basic Pitch on this machine. Same cleaner → CMR → grand-staff path as before.

### Quality (MR-MT3)

Quality never falls back to Fast. Configure a GPU worker **or** a command that writes **MIDI** (not MusicXML):

```env
MT3_ENDPOINT=http://127.0.0.1:8090/transcribe
MT3_API_KEY=
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

`GET /health` includes `quality.available`. The UI greys out Quality until a worker is configured.
