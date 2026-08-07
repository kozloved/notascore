#!/usr/bin/env bash
# Bootstrap NotaScore on a Linux origin behind Cloudflare Tunnel.
# Usage:
#   CLOUDFLARE_TUNNEL_TOKEN=... EMAIL=you@example.com ./deploy/bootstrap.sh
#
# EMAIL is optional (kept for compatibility with older Oracle/LE flows).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/kozloved/notascore.git}"
APP_DIR="${APP_DIR:-$HOME/notascore/audio2score-week4}"
TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "Set CLOUDFLARE_TUNNEL_TOKEN to the Cloudflare Tunnel token." >&2
  echo "Create one in Zero Trust → Networks → Tunnels." >&2
  exit 1
fi

if [[ ! -d "$APP_DIR" ]]; then
  git clone "$REPO_URL" "$HOME/notascore"
fi

cd "$APP_DIR"

if [[ ! -f .env.production ]]; then
  cp .env.production.example .env.production
fi

if ! grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.\+' .env.production; then
  # Replace empty token line or append.
  if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=' .env.production; then
    sed -i.bak "s|^CLOUDFLARE_TUNNEL_TOKEN=.*|CLOUDFLARE_TUNNEL_TOKEN=${TOKEN}|" .env.production
    rm -f .env.production.bak
  else
    printf '\nCLOUDFLARE_TUNNEL_TOKEN=%s\n' "$TOKEN" >> .env.production
  fi
fi

cp nginx/notascore.cloudflare.conf nginx/notascore.conf
docker compose --env-file .env.production --profile cloudflare up -d --build

echo "Done. Check: https://notascore.com and https://notascore.com/api/health"
echo "Tunnel logs: docker compose --env-file .env.production --profile cloudflare logs -f cloudflared"
