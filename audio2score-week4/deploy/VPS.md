# Deploy NotaScore on a cheap VPS (~$5–6/month)

This is the production path for the **CPU site**: Next.js + FastAPI + Redis + Solo worker.
**Polyphonic / YourMT3 stays on Vast.ai.** Do not install the GPU worker on the VPS.

```text
Browser
  → Cloudflare (HTTPS)
       → Cloudflare Tunnel
            → VPS nginx :80  (bound to localhost only)
                 → frontend :3000
                 → api :8000  +  RQ worker  +  Redis
                            │
                            │  Polyphonic jobs only
                            ▼
                      Vast.ai GPU  POST /transcribe
```

Cost: a Hetzner **CX22** is about **€4–5/month** (2 vCPU, 4 GB RAM). Cloudflare Tunnel and the domain stay on the free plan. That replaces Render (~$42/month).

A CX22 is tight for Solo (Basic Pitch). The setup script adds **2 GB swap**. If Solo jobs get killed (`Killed` / exit 137), resize to **CX32** (8 GB, ~€7–8/month).

---

## 1. Create the VPS (Hetzner)

1. Sign in at [console.hetzner.cloud](https://console.hetzner.cloud/).
2. **New project** → **Add server**.
3. Location: closest to you (or `ash` / `hil` if most users are in the US).
4. Image: **Ubuntu 24.04**.
5. Type: **CX22** (or CX32 if you want more RAM from day one).
6. Networking: leave **IPv4** enabled (needed for `apt` and cloning).
7. SSH key: add your public key (`ssh-add -L` / `~/.ssh/id_ed25519.pub`).
8. Name it `notascore`. Create.

Copy the IPv4 address. From your laptop:

```bash
ssh root@YOUR_VPS_IP
```

Hetzner Cloud Firewall (optional but good): inbound **TCP 22** only. Do **not** open 80 or 443. The tunnel does not need them.

---

## 2. Install Docker and swap

On the VPS, as root:

```bash
apt-get update && apt-get install -y git
git clone https://github.com/kozloved/notascore.git
cd notascore
sudo bash audio2score-week4/deploy/vps-setup.sh
```

That script:

- installs **Docker Engine** and the Compose plugin
- adds a **2 GB swapfile** if the box has no swap
- enables **UFW** with SSH only (no public HTTP)

Log out and back in if `docker` says you are not in the `docker` group (the script adds `root` and, if present, `ubuntu`).

Check:

```bash
docker version
docker compose version
free -h
```

---

## 3. Put `notascore.com` on Cloudflare

Skip this if the domain is already on Cloudflare.

1. [dash.cloudflare.com](https://dash.cloudflare.com/) → **Add a site** → `notascore.com`.
2. Free plan is enough.
3. At your registrar, set the two Cloudflare **nameservers**.
4. Wait until the zone is **Active**.

If you pointed `@` / `www` at Render (`*.onrender.com`), delete those records after the tunnel is up (step 7). Do not point an A record at the VPS IP.

---

## 4. Create the Cloudflare Tunnel

1. Cloudflare → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel**.
2. Connector: **Cloudflared**. Name: `notascore-vps`. Save.
3. Copy the **tunnel token** (long string). You will paste it into `.env.production`.
4. You can skip the “install connector” commands Cloudflare shows. Compose runs `cloudflared`.
5. **Public Hostname** → add two rows:

| Subdomain | Domain | Type | URL |
|---|---|---|---|
| *(empty)* | notascore.com | HTTP | `http://nginx:80` |
| `www` | notascore.com | HTTP | `http://nginx:80` |

`http://nginx:80` is the Compose service name, not a public URL.

6. Domain **SSL/TLS** mode: **Full** (not Full Strict unless you later put a real cert on nginx). The tunnel is encrypted; nginx inside Docker is HTTP.

---

## 5. Configure and start the site

On the VPS:

```bash
cd /root/notascore/audio2score-week4   # or wherever you cloned
cp .env.production.example .env.production
nano .env.production
```

Set at least:

```env
CLOUDFLARE_TUNNEL_TOKEN=paste_the_token
NEXT_PUBLIC_API_URL=/api
CORS_ORIGIN=https://notascore.com,https://www.notascore.com
```

Leave `MT3_ENDPOINT` empty until a GPU worker is configured. Solo works without a GPU.

For RunPod Serverless YourMT3:

```env
MT3_ENDPOINT=https://api.runpod.ai/v2/g40wir5ey71e3/runsync
MT3_API_KEY=<RunPod API key>
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

Keep `MT3_API_KEY` in `.env.production` on the VPS only. Never commit it.

Start:

```bash
./deploy/start-local-tunnel.sh
```

First build takes several minutes (Basic Pitch / madmom). Watch:

```bash
docker compose --env-file .env.production --profile tunnel ps
curl -fsS http://127.0.0.1/api/health
docker compose --env-file .env.production --profile tunnel logs -f cloudflared
```

`/api/health` should show `"status":"ok"` and `"modes":{"solo":true,...}`.

Then from your laptop:

```bash
curl -fsS https://notascore.com/api/health
```

Open `https://notascore.com` and upload a short Solo `.wav`.

---

## 6. Point Polyphonic at RunPod Serverless (or Vast.ai)

On the VPS, edit `.env.production`.

RunPod Serverless:

```env
MT3_ENDPOINT=https://api.runpod.ai/v2/g40wir5ey71e3/runsync
MT3_API_KEY=<RunPod API key>
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

Legacy Vast.ai HTTP worker:

```env
MT3_ENDPOINT=http://<vast-public-ip>:<mapped-port>/transcribe
MT3_API_KEY=the-same-secret-as-the-gpu
MT3_MODEL=yourmt3
```

```bash
docker compose --env-file .env.production --profile tunnel up -d api worker
curl -fsS http://127.0.0.1/api/health
# modes.polyphonic should be true
# polyphonic.provider should be runpod when using api.runpod.ai
```

GPU HTTP worker setup: [../gpu-worker/README.md](../gpu-worker/README.md). Destroy a Vast.ai instance when you are not using it.

---

## 7. Leave Render (stop the $42 bill)

Only after `https://notascore.com/api/health` works through the tunnel:

1. Cloudflare DNS: delete CNAME/A records that target `*.onrender.com`. The tunnel creates its own `CNAME` for `@` and `www`.
2. Render Dashboard → delete `notascore-frontend`, `notascore-backend`, `notascore-redis` (or the whole Blueprint project).
3. Confirm Render billing shows no running services.

---

## 8. Updates

```bash
cd /root/notascore
git pull origin main
cd audio2score-week4
./deploy/start-local-tunnel.sh
```

Volumes (`dbdata`, `uploads`, `results`) survive rebuilds.

---

## 9. Smoke test

```bash
BASE_URL=https://notascore.com/api ./deploy/smoke-test.sh
```

---

## What not to do

- Do not deploy `gpu-worker/` on the VPS (`--profile gpu`).
- Do not open ports 80/443 on the VPS. Nginx listens on `127.0.0.1:80` for local checks only.
- Do not put an A record to the VPS IP. The tunnel hides the origin.
- Do not skip swap on a 4 GB box. Solo will OOM without it.
