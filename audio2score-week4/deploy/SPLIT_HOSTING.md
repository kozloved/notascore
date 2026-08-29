# Split hosting: CPU site + GPU worker

The website and the transcription GPU are **different machines**.

```text
Browser
  → Cloudflare Tunnel
       → VPS (Docker Compose: nginx + Next.js + FastAPI + Redis + Solo worker)
                            │
                            │  Polyphonic jobs only: POST audio, get MIDI
                            ▼
       Vast.ai GPU  (YourMT3 via mt3-infer 0.2.0)
```

| Piece | Where | GPU? | Cost |
|---|---|---|---|
| Site (frontend + API + Redis + Solo jobs) | Cheap VPS + Cloudflare Tunnel | No | ~$5–6/month (Hetzner CX22) |
| Polyphonic model | Vast.ai dedicated GPU | Yes | Paid by the hour; destroy when idle |

**RunPod is not free.** Prefer Vast.ai for the GPU and a VPS for the site.

## 1. Site (CPU) — VPS

Follow [VPS.md](VPS.md). Compose starts Redis, API, worker, frontend, nginx, and `cloudflared`.

```env
MT3_ENDPOINT=http://<vast-public-ip>:<mapped-port>/transcribe
MT3_API_KEY=the-same-secret-as-the-gpu
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

`GET https://notascore.com/api/health` should show `modes.polyphonic: true` after the GPU worker is up.

Do **not** put FastAPI on a GPU pod just to serve the website.

## 2. GPU (Vast.ai)

Follow [../gpu-worker/README.md](../gpu-worker/README.md). Short version:

1. Rent an RTX 3060 12 GB (or better) with a PyTorch CUDA 12 template and port **8090** open.
2. Copy `audio2score-week4/gpu-worker/` onto the instance.
3. `export MT3_API_KEY=...` and run `./vast.onstart.sh`.
4. Confirm `curl http://127.0.0.1:8090/health` reports `"cuda": true` and `"model": "yourmt3"`.
5. Paste the public `IP:PORT` into `MT3_ENDPOINT` on the VPS and recreate `api` + `worker`.

Optional: `docker compose --profile gpu` on a machine that **has** an NVIDIA GPU. Remote Vast.ai does not use that profile — only `MT3_ENDPOINT`.

## 3. Modes

| UI | Engine | Runs on |
|---|---|---|
| Solo | Basic Pitch | CPU site (VPS) |
| Polyphonic | YourMT3 (`mt3-infer` 0.2.0) | Vast.ai GPU |

Legacy API values `fast` and `quality` still work (`fast` → Solo, `quality` → Polyphonic).
