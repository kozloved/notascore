# Deploy NotaScore

## Oracle Cloud (recommended for production)

Always-on **Oracle Always Free** VM — no laptop, no tunnel connector.

**[deploy/oracle/README.md](oracle/README.md)** — full OCI setup (VM, firewall, DNS, bootstrap).

Quick start on the VM:

```bash
MODE=cloudflare DOMAIN=notascore.com ./deploy/oracle/bootstrap.sh
```

---

## Local machine + Cloudflare Tunnel

Run the full stack (Nginx → Next.js + FastAPI + Redis + worker) on your Mac/PC.
Cloudflare Tunnel exposes `https://notascore.com` without opening router ports.

```text
Browser → Cloudflare (HTTPS) → tunnel → cloudflared → nginx:80 → frontend /api
```

## 1. Put `notascore.com` on Cloudflare

1. Create a free account at [dash.cloudflare.com](https://dash.cloudflare.com/).
2. **Add a site** → enter `notascore.com`.
3. Cloudflare shows two **nameservers**. At your domain registrar, replace the current nameservers with Cloudflare’s.
4. Wait until the domain status is **Active** (often 5–30 minutes, sometimes longer).

You do **not** need an A record to your home IP. The tunnel will create the DNS records.

## 2. Create a Cloudflare Tunnel

1. In Cloudflare: **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel**.
2. Choose **Cloudflared** → name it e.g. `notascore-local` → **Save**.
3. Copy the **tunnel token** (long string). You will put it in `.env.production`.
4. Under **Public Hostname**, add:

| Subdomain | Domain | Service |
|-----------|--------|---------|
| *(empty)* | notascore.com | `http://nginx:80` |
| `www` | notascore.com | `http://nginx:80` |

Use `http://nginx:80` because `cloudflared` runs inside Docker Compose on the same network as Nginx.

5. SSL/TLS mode for the domain: **Full** (tunnel is encrypted; origin is HTTP inside Docker).

## 3. Start the local stack

On the machine that will stay on while the site is public:

```bash
cd /path/to/notascore/audio2score-week4
cp .env.production.example .env.production
```

Edit `.env.production` and set:

```env
CLOUDFLARE_TUNNEL_TOKEN=paste_token_here
NEXT_PUBLIC_API_URL=https://notascore.com/api
CORS_ORIGIN=https://notascore.com,https://www.notascore.com
```

Use the HTTP Nginx config (Cloudflare terminates HTTPS):

```bash
cp nginx/notascore.http.conf nginx/notascore.conf
docker compose --env-file .env.production --profile tunnel up -d --build
```

Or:

```bash
./deploy/start-local-tunnel.sh
```

Check:

```bash
curl -fsS http://localhost/api/health
docker compose logs -f cloudflared
curl -fsS https://notascore.com/api/health
```

## 4. Smoke test

```bash
BASE_URL=https://notascore.com/api ./deploy/smoke-test.sh
# or open https://notascore.com and upload a short .wav
docker compose logs -f worker
```

## 5. Ongoing updates

```bash
cd /path/to/notascore/audio2score-week4
git pull origin main
cp nginx/notascore.http.conf nginx/notascore.conf   # keep HTTP origin behind the tunnel
docker compose --env-file .env.production --profile tunnel up -d --build
```

## API proxy mapping

| Browser | Nginx | FastAPI |
|---------|-------|---------|
| `https://notascore.com/api/upload` | `location /api/` → `proxy_pass http://api:8000/` | `POST /upload` |
| `https://notascore.com/api/jobs/{id}` | same | `GET /jobs/{id}` |
| `https://notascore.com/api/jobs/{id}/result` | same | `GET /jobs/{id}/result` |

## Notes

- Keep the machine awake (disable sleep while serving) or the site goes offline.
- Redis is Docker-network only (not published).
- Do not commit `.env.production` (contains the tunnel token).
- Optional: remove published `443` from Compose if you never use local TLS; port `80` is handy for local checks.
- For Oracle + Let's Encrypt on the VM, use `deploy/oracle/bootstrap.sh` with `MODE=letsencrypt` or `deploy/init-tls.sh`.
