# Deploy NotaScore

The **CPU site** (Nginx → Next.js + FastAPI + Redis + Solo worker) runs on a cheap VPS behind **Cloudflare Tunnel**.
**Polyphonic (YourMT3) stays on Vast.ai.**

```text
Browser → Cloudflare (HTTPS) → tunnel → cloudflared → nginx:80 → frontend /api
```

| Guide | Use when |
|---|---|
| **[VPS.md](VPS.md)** | Production: Hetzner-class VPS (~$5–6/month). Start here. |
| [SPLIT_HOSTING.md](SPLIT_HOSTING.md) | How the VPS and Vast.ai GPU fit together |
| [../gpu-worker/README.md](../gpu-worker/README.md) | Rent and start YourMT3 |

## Quick start (after the VPS exists)

```bash
cd audio2score-week4
cp .env.production.example .env.production
# set CLOUDFLARE_TUNNEL_TOKEN
./deploy/start-local-tunnel.sh
curl -fsS http://127.0.0.1/api/health
```

First-time Ubuntu box: [VPS.md](VPS.md) steps 1–5, or `sudo bash deploy/vps-setup.sh`.

## API proxy mapping

| Browser | Nginx | FastAPI |
|---------|-------|---------|
| `https://notascore.com/api/upload` | `location /api/` → `proxy_pass http://api:8000/` | `POST /upload` |
| `https://notascore.com/api/jobs/{id}` | same | `GET /jobs/{id}` |
| `https://notascore.com/api/jobs/{id}/result` | same | `GET /jobs/{id}/result` |

## Notes

- Nginx is bound to `127.0.0.1:80`. Do not open 80/443 on the VPS.
- Redis is Docker-network only.
- Do not commit `.env.production` (contains the tunnel token).
