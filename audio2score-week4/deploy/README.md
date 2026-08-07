# Deploy NotaScore (notascore.com)

**Recommended edge: Cloudflare Tunnel.** The app (Next.js + FastAPI + Redis + RQ) runs on any Linux origin; Cloudflare terminates TLS and publishes `notascore.com`.

There are **no leftover Cloudflare configs from earlier attempts** in this repo — DNS for `notascore.com` was still on Spaceship parking hosts when this path was added. Oracle Always Free remains an optional cheap origin, not the edge.

```text
Internet → Cloudflare (TLS + DNS)
         → cloudflared tunnel
         → Nginx :80 → frontend :3000
                     → api :8000
                     → redis + worker (internal)
```

## 0. Cloudflare DNS (do this first)

1. Add the domain in [Cloudflare](https://dash.cloudflare.com/) (Free plan is enough).
2. At your registrar (currently Spaceship), replace nameservers with the two Cloudflare NS hosts Cloudflare shows.
3. In Cloudflare DNS, you do **not** need public A records pointing at the origin when using a Tunnel — the Tunnel creates the route. For `www`, either:
   - CNAME `www` → `notascore.com` (proxied), or
   - add both hostnames as Tunnel public hostnames (step 2 below).
4. SSL/TLS mode: **Full** (Tunnel speaks HTTPS to visitors; origin is HTTP over the tunnel).

## 1. Create a Cloudflare Tunnel

In Zero Trust → **Networks → Tunnels**:

1. Create a tunnel (e.g. `notascore`).
2. Choose **Cloudflared** / Docker install and copy the **tunnel token**.
3. Under Public Hostname, add:
   - `notascore.com` → `http://nginx:80`
   - `www.notascore.com` → `http://nginx:80`  
   (service hostname `nginx` is the Compose service name on the `notascore` network.)

Put the token in `.env.production` as `CLOUDFLARE_TUNNEL_TOKEN=...`.

## 2. Origin host (any Linux box)

Oracle Ampere, a small VPS, or a home lab machine all work. The origin does **not** need ports 80/443 open when using Tunnel (outbound-only).

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# log out and back in so docker works without sudo
```

## 3. Clone, configure, start with Cloudflare

```bash
cd ~
git clone https://github.com/kozloved/notascore.git
cd notascore/audio2score-week4

cp .env.production.example .env.production
# Edit .env.production:
#   CLOUDFLARE_TUNNEL_TOKEN=<token from step 1>
#   NEXT_PUBLIC_API_URL / CORS_ORIGIN already target https://notascore.com

cp nginx/notascore.cloudflare.conf nginx/notascore.conf

# --env-file loads CLOUDFLARE_TUNNEL_TOKEN for the cloudflared service
docker compose --env-file .env.production --profile cloudflare up -d --build
```

Smoke:

```bash
curl -fsS https://notascore.com/ | head
curl -fsS https://notascore.com/api/health
BASE_URL=https://notascore.com/api ./deploy/smoke-test.sh
docker compose --env-file .env.production --profile cloudflare logs -f cloudflared worker
```

## 4. Ongoing updates

```bash
cd ~/notascore/audio2score-week4
git pull origin main
cp nginx/notascore.cloudflare.conf nginx/notascore.conf
docker compose --env-file .env.production --profile cloudflare up -d --build
```

## API proxy mapping

| Browser | Nginx | FastAPI |
|---------|-------|---------|
| `https://notascore.com/api/upload` | `location /api/` → `proxy_pass http://api:8000/` | `POST /upload` |
| `https://notascore.com/api/jobs/{id}` | same | `GET /jobs/{id}` |
| `https://notascore.com/api/jobs/{id}/result` | same | `GET /jobs/{id}/result` |

- Frontend build: `NEXT_PUBLIC_API_URL=https://notascore.com/api`
- Backend CORS: `CORS_ORIGIN=https://notascore.com,https://www.notascore.com`

## Alternative A — Cloudflare orange-cloud (no Tunnel)

Point proxied A/AAAA records at a public origin IP and keep origin Nginx on :80 with `notascore.cloudflare.conf`. Set SSL mode to **Flexible** only if the origin has no cert (not ideal); prefer Tunnel or Full with an origin cert.

You still need inbound **80** (and usually **443**) on the origin firewall.

## Alternative B — Classic Let's Encrypt on the origin (no Cloudflare)

Use the HTTP → ACME → TLS configs if you want the origin to terminate TLS itself (e.g. direct VPS DNS, no Cloudflare):

```bash
cp nginx/notascore.http.conf nginx/notascore.conf
docker compose up -d --build
EMAIL=you@example.com ./deploy/init-tls.sh
# optional renew loop:
docker compose --profile certbot up -d certbot
```

## Optional: Oracle Always Free as the origin

Oracle is only the compute box. After the Ampere VM exists:

1. Follow §2–3 above (Cloudflare Tunnel preferred — no need to open 80/443 in the VCN).
2. If you skip Tunnel and expose the VM directly, allow inbound **22, 80, 443** and use Alternative B.

## Notes

- Redis stays on the Docker network only (not published).
- Uploads / results / SQLite use named Docker volumes.
- First Basic Pitch image build can take a long time on small ARM VMs.
- Do **not** run MR-MT3 on a free mini VM (needs a separate GPU host later).
- Local packaging check without Cloudflare:

```bash
cp nginx/notascore.http.conf nginx/notascore.conf
cp .env.production.example .env.production
# leave CLOUDFLARE_TUNNEL_TOKEN empty / unused without the profile
NEXT_PUBLIC_API_URL=http://localhost/api CORS_ORIGIN=http://localhost \
  docker compose up -d --build
curl -fsS http://localhost/api/health
```
