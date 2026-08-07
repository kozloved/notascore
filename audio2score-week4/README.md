# NotaScore

NotaScore AI turns uploaded audio into editable MusicXML via the NotaScore Transcription Engine.

## Production deploy (Cloudflare)

See [deploy/README.md](deploy/README.md) for Docker Compose + Nginx behind a **Cloudflare Tunnel** (recommended). Oracle Always Free is an optional origin host; TLS/DNS stay on Cloudflare.

## What is included?

- Redis Queue worker
- Storage abstraction
- Transcription engine system
- Placeholder MT3 engine by default
- Command-based MT3 engine option
- Example MT3 command script
- Worker that calls the transcription engine
- Frontend that shows engine info

## Project Structure

```text
audio2score-week4/
  backend/          FastAPI + RQ worker + Basic Pitch
  frontend/         Next.js (TypeScript) upload + sheet preview UI
  nginx/            HTTP / TLS / Cloudflare origin configs
  deploy/           Cloudflare Tunnel bootstrap + smoke tests
  docker-compose.yml
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

## Transcription Engines

The NotaScore Transcription Engine supports two modes.

### Placeholder mode

This is the default.

```env
TRANSCRIPTION_ENGINE=placeholder
```

It generates placeholder MusicXML.

### Command mode

Use this when you have a real MT3 command or script.

```env
TRANSCRIPTION_ENGINE=command
MT3_TRANSCRIBE_COMMAND=python scripts/example_mt3.py {input} {output}
MT3_TIMEOUT_SECONDS=300
```

The command must:

1. Read the input audio file from `{input}`.
2. Write MusicXML output to `{output}`.

## Example MT3 Script

An example command script is included:

```text
backend/scripts/example_mt3.py
```

To test it, set:

```env
TRANSCRIPTION_ENGINE=command
MT3_TRANSCRIBE_COMMAND=python scripts/example_mt3.py {input} {output}
```

Then restart the API and worker.
