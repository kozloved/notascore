# Audio2Score — Week 4

Week 4 adds a transcription engine adapter.

## What is new in Week 4?

- Redis Queue worker from Week 3 remains.
- Storage abstraction from Week 3 remains.
- New transcription engine system.
- Placeholder MT3 engine by default.
- Command-based MT3 engine option.
- Example MT3 command script.
- Updated worker to call the transcription engine.
- Updated frontend to show engine info.

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

## Transcription Engines

Week 4 supports two engine modes.

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
