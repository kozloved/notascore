# Split hosting: CPU site + GPU worker

The website and the transcription GPU are **different machines**.

```text
Browser
  → Render frontend (Next.js, public)
       /api  →  Render backend (FastAPI + Solo worker + disk)
                      Redis (Key Value)
                            │
                            │  Polyphonic jobs only: POST audio, get MIDI
                            ▼
       Vast.ai GPU  (YourMT3 via mt3-infer 0.2.0)
```

| Piece | Where | GPU? | Cost |
|---|---|---|---|
| Site (frontend + API + Redis + Solo jobs) | **Render** (recommended) or Docker Compose + Cloudflare Tunnel | No | Render Starter/Standard; cheaper than a GPU pod |
| Polyphonic model | Vast.ai dedicated GPU | Yes | Paid by the hour; destroy when idle |

**RunPod is not free.** Prefer Vast.ai for the GPU and Render for the site.

## 1. Site (CPU) — Render

Follow [RENDER.md](RENDER.md). Blueprint `render.yaml` at the repo root creates Redis, one backend service (`./start-web.sh` = FastAPI + worker + `/data` disk), and one frontend that proxies `/api` to the backend private `host:port`.

```env
MT3_ENDPOINT=http://<vast-public-ip>:<mapped-port>/transcribe
MT3_API_KEY=the-same-secret-as-the-gpu
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

`GET /api/health` on the Render frontend should show `modes.polyphonic: true` after the GPU worker is up.

### Alternative: Compose + Cloudflare Tunnel

Use the existing Compose stack from [README.md](README.md):

```bash
cd audio2score-week4
cp .env.production.example .env.production
# set CLOUDFLARE_TUNNEL_TOKEN, CORS_ORIGIN, and the MT3_* vars from step 2
cp nginx/notascore.http.conf nginx/notascore.conf
docker compose --env-file .env.production --profile tunnel up -d --build
```

That is the always-on local path: Cloudflare Tunnel + a machine that stays awake. Do **not** put FastAPI on a GPU pod just to serve the website.

After the GPU worker is up, set these on the CPU host:

```env
MT3_ENDPOINT=http://<vast-public-ip>:<mapped-port>/transcribe
MT3_API_KEY=the-same-secret-as-the-gpu
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

Restart `api` and `worker`. `GET /api/health` should show `modes.polyphonic: true`.

## 2. GPU (Vast.ai)

Follow [../gpu-worker/README.md](../gpu-worker/README.md). Short version:

1. Rent an RTX 3060 12 GB (or better) with a PyTorch CUDA 12 template and port **8090** open.
2. Copy `audio2score-week4/gpu-worker/` onto the instance.
3. `export MT3_API_KEY=...` and run `./vast.onstart.sh`.
4. Confirm `curl http://127.0.0.1:8090/health` reports `"cuda": true` and `"model": "yourmt3"`.
5. Paste the public `IP:PORT` into `MT3_ENDPOINT` on the site.

Optional: `docker compose --profile gpu` on a machine that **has** an NVIDIA GPU. Remote Vast.ai does not use that profile — only `MT3_ENDPOINT`.

## 3. Modes

| UI | Engine | Runs on |
|---|---|---|
| Solo | Basic Pitch | CPU site (Render) |
| Polyphonic | YourMT3 (`mt3-infer` 0.2.0) | Vast.ai GPU |

Legacy API values `fast` and `quality` still work (`fast` → Solo, `quality` → Polyphonic).
