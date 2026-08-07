#!/usr/bin/env bash
# Start NotaScore locally with Cloudflare Tunnel (HTTP origin).
# Requires CLOUDFLARE_TUNNEL_TOKEN in .env.production
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.production ]]; then
  cp .env.production.example .env.production
  echo "Created .env.production — add CLOUDFLARE_TUNNEL_TOKEN, then re-run." >&2
  exit 1
fi

if ! grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=.+' .env.production; then
  echo "Set CLOUDFLARE_TUNNEL_TOKEN in .env.production" >&2
  exit 1
fi

cp nginx/notascore.http.conf nginx/notascore.conf

docker compose --env-file .env.production --profile tunnel up -d --build

echo "Local health:  curl -fsS http://localhost/api/health"
echo "Public health: curl -fsS https://notascore.com/api/health"
echo "Tunnel logs:   docker compose logs -f cloudflared"
