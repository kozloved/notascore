# Deploy the CPU site on Render

The **website, API, Redis, and Solo (Basic Pitch) worker** run on Render.
**Polyphonic / YourMT3 stays on Vast.ai.** Do not add the GPU worker to this project.

```text
Browser
  → Render frontend  (Next.js, public)
       /api/*  →  notascore-backend:10000  (FastAPI + RQ worker)
                      Render Key Value (Redis)
                      Disk /data  (sqlite + uploads + results)
                            │
                            │  Polyphonic jobs only
                            ▼
                      Vast.ai GPU  POST /transcribe
```

Render free web services spin down after idle time. Use **Starter** (frontend) and **Standard** (backend, ~2 GB) so Solo transcription does not OOM. Cheaper than a GPU pod; not $0.

## 1. Create from Blueprint

1. Push this branch (or merge to the branch Render tracks).
2. Sign in at [dashboard.render.com](https://dashboard.render.com/).
3. **New** → **Blueprint**.
4. Select the `kozloved/notascore` repo. Render reads `render.yaml` at the repo root.
5. Fill in secrets when prompted:
   - `MT3_ENDPOINT` — Vast.ai `http://IP:PORT/transcribe` (leave blank until the GPU is up)
   - `MT3_API_KEY` — same secret as the GPU worker
6. Apply. Render creates `notascore-redis`, `notascore-backend`, and `notascore-frontend`.

The backend runs **API + RQ worker in one container** (`./start-web.sh`) with a 1 GB disk at `/data`. Render cannot attach that disk to a second service.

## 2. What the Blueprint sets

| Service | Plan | Notes |
|---|---|---|
| `notascore-redis` | Starter Key Value | `REDIS_URL` on the backend (private connection string) |
| `notascore-backend` | Standard | Docker, `./start-web.sh`, health `/health`, disk `/data` |
| `notascore-frontend` | Starter | Docker, `BACKEND_URL` = backend private `host:port`, browser uses `/api` |

`app/api/[...path]/route.ts` prefixes `http://` if `BACKEND_URL` is Render’s `hostport` value (`notascore-backend:10000`).

## 3. Custom domain

Frontend service → **Settings** → **Custom domains** → `notascore.com`.

Cloudflare DNS (stop using the old tunnel for this hostname):

| Type | Name | Target |
|---|---|---|
| CNAME | `@` | `notascore-frontend.onrender.com` (CNAME flattening on) |
| CNAME | `www` | same |

`CORS_ORIGIN` already includes `https://notascore.com`. The backend also allows `FRONTEND_PUBLIC_URL` (the Render frontend URL).

## 4. Point Polyphonic at Vast.ai

On **notascore-backend** → Environment:

```env
MT3_ENDPOINT=http://<vast-public-ip>:<mapped-port>/transcribe
MT3_API_KEY=...
MT3_MODEL=yourmt3
```

Manual deploy of the backend. `https://<frontend>/api/health` should show `modes.polyphonic: true`.

GPU setup: [../gpu-worker/README.md](../gpu-worker/README.md).

## 5. Check

```bash
curl -sS https://<frontend-onrender>/api/health
# status ok, modes.solo true
```

Solo transcribes on Render CPU. Polyphonic reaches Vast.ai.

## What not to do

- Do not deploy `gpu-worker/` on Render (no GPU).
- Do not split API and worker into two Render services unless you switch storage to Supabase. They cannot share a disk.
- Do not use a Free web plan for the backend: it sleeps, and Basic Pitch needs more RAM than the Free instance.
