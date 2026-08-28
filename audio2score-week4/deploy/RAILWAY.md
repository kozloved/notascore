# Deploy the CPU site on Railway

The **website, API, Redis, and Solo (Basic Pitch) worker** run on Railway.
**Polyphonic / YourMT3 stays on Vast.ai.** Do not add the GPU worker to this project.

```text
Browser
  → Railway frontend  (Next.js, public)
       /api/*  →  Railway backend.railway.internal  (FastAPI + RQ worker)
                      Redis plugin (private)
                      Volume /data  (sqlite + uploads + results)
                            │
                            │  Polyphonic jobs only
                            ▼
                      Vast.ai GPU  POST /transcribe
```

Railway is a paid Hobby plan (not permanently free). It is still cheaper than a GPU pod for the site.

## 1. Create the project

1. Sign in at [railway.com](https://railway.com/).
2. **New project** → **Empty project**.
3. Name it `notascore`.

## 2. Add Redis

**New** → **Database** → **Redis**.

Copy the variable `REDIS_PRIVATE_URL` (or `REDIS_URL`). The backend prefers `REDIS_PRIVATE_URL`.

## 3. Backend service (API + Solo worker)

**New** → **GitHub repo** → this repository.

| Setting | Value |
|---|---|
| Root directory | `audio2score-week4/backend` |
| Builder | Dockerfile |
| Start command | `./start-railway.sh` |
| Public networking | **on** (or off if you only proxy via frontend; keep on until the frontend works) |
| Health check path | `/health` |
| Volume | mount path `/data` (1 GB is enough for MVP) |
| Memory | **2 GB** (Basic Pitch + madmom) |

API and the RQ worker run in **one** container so they share `/data`. Railway volumes cannot be attached to two services.

Variables (Variables tab → Raw editor):

```env
DATABASE_URL=sqlite:////data/audio2score.db
UPLOAD_DIR=/data/uploads
RESULTS_DIR=/data/results
TEMP_DIR=/data/tmp
REDIS_URL=${{Redis.REDIS_URL}}
REDIS_PRIVATE_URL=${{Redis.REDIS_PRIVATE_URL}}
QUEUE_NAME=transcription
CORS_ORIGIN=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}},https://notascore.com,https://www.notascore.com
MAX_UPLOAD_MB=25
TRANSCRIPTION_PIPELINE=understanding
TRANSCRIPTION_PIPELINE_FALLBACK=1
TRANSCRIPTION_BACKEND=basic_pitch
TRANSCRIPTION_USE_CLEANER=1
TRANSCRIPTION_USE_NORMALIZER=1
TRANSCRIPTION_USE_BEAT_TRACKER=1
TRANSCRIPTION_USE_PIANO_ANALYZER=1
TRANSCRIPTION_USE_MIR_LAYERS=1
MT3_ENDPOINT=https://YOUR-VAST-IP:PORT/transcribe
MT3_API_KEY=the-same-secret-as-the-gpu
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

`${{Redis.REDIS_URL}}` is Railway’s service reference. Rename `Redis` / `frontend` if your service names differ.

Generate a domain for the backend (Settings → Networking → Generate domain) so you can hit `/health` during setup.

## 4. Frontend service

**New** → same GitHub repo.

| Setting | Value |
|---|---|
| Root directory | `audio2score-week4/frontend` |
| Builder | Dockerfile |
| Public networking | **on** |
| Custom domain | `notascore.com` and `www.notascore.com` |

Variables:

```env
NEXT_PUBLIC_API_URL=/api
BACKEND_URL=http://backend.railway.internal:${{backend.PORT}}
HOSTNAME=::
```

If the backend service is not named `backend`, use `http://<service-name>.railway.internal:PORT`. Railway injects `PORT` on the backend; if the reference is empty, use `http://backend.railway.internal:8000` and set the backend start port by leaving `PORT` as Railway assigns it.

**Important:** the frontend talks to the backend on the **private** network. `BACKEND_URL` must be `http://….railway.internal:…`, not the public `*.up.railway.app` URL.

The browser keeps calling `/api/...` on the frontend origin. `app/api/[...path]/route.ts` proxies to FastAPI.

## 5. Custom domain (notascore.com)

In Cloudflare DNS (stop using the old tunnel for this hostname):

| Type | Name | Target |
|---|---|---|
| CNAME | `@` | Railway frontend domain (`….up.railway.app`) if Cloudflare CNAME flattening is on |
| CNAME | `www` | same |

In Railway frontend → **Custom domain** → `notascore.com`. SSL is issued by Railway.

Then set backend `CORS_ORIGIN` to include `https://notascore.com`.

## 6. Point Polyphonic at Vast.ai

On the **backend** service only:

```env
MT3_ENDPOINT=http://<vast-public-ip>:<mapped-port>/transcribe
MT3_API_KEY=...
MT3_MODEL=yourmt3
```

Redeploy backend. `https://<frontend>/api/health` should show `modes.polyphonic: true`.

GPU setup: [../gpu-worker/README.md](../gpu-worker/README.md).

## 7. Check

```bash
curl -sS https://<frontend-domain>/api/health
# status ok, modes.solo true
# modes.polyphonic true only after MT3_ENDPOINT is set
```

Open the site, Solo should transcribe on Railway CPU. Polyphonic should reach Vast.ai.

## Optional: import from Compose

`audio2score-week4/docker-compose.railway.yml` maps to the same two services. Drag it onto the Railway canvas, then **still** add a managed Redis plugin and a `/data` volume on `backend`. Compose Redis is not a substitute for Railway Redis.

## What not to do

- Do not deploy `gpu-worker/` on Railway (no GPU).
- Do not run API and worker as two Railway services unless you switch storage to Supabase (`SUPABASE_URL` + service role). They cannot share a volume.
- Do not put FastAPI `DATABASE_URL` on the ephemeral disk without a volume — restarts wipe jobs.
