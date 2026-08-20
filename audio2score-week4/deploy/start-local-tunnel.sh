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

docker compose --env-file .env.production --profile tunnel up -d --build --remove-orphans

echo "Waiting for local origin on http://localhost/api/health ..."
ok=0
for _ in $(seq 1 45); do
  if curl -fsS --max-time 3 http://127.0.0.1/api/health >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "$ok" -ne 1 ]]; then
  echo "ERROR: local origin did not become healthy. Last compose status:" >&2
  docker compose --env-file .env.production --profile tunnel ps >&2 || true
  echo "--- nginx ---" >&2
  docker compose --env-file .env.production --profile tunnel logs --tail=40 nginx >&2 || true
  echo "--- cloudflared ---" >&2
  docker compose --env-file .env.production --profile tunnel logs --tail=40 cloudflared >&2 || true
  exit 1
fi

echo "Local health:  curl -fsS http://localhost/api/health"
echo "Public health: curl -fsS https://notascore.com/api/health"
echo "Tunnel logs:   docker compose --env-file .env.production --profile tunnel logs -f cloudflared"
