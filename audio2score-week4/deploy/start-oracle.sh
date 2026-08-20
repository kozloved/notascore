#!/usr/bin/env bash
# Start or update NotaScore on an Oracle VM (no Cloudflare Tunnel).
#
# Usage:
#   MODE=cloudflare ./deploy/start-oracle.sh
#   MODE=letsencrypt EMAIL=you@example.com ./deploy/start-oracle.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${MODE:-cloudflare}"
DOMAIN="${DOMAIN:-notascore.com}"

if [[ ! -f .env.production ]]; then
  cp .env.production.example .env.production
  echo "Created .env.production — review values, then re-run." >&2
  exit 1
fi

if [[ "$MODE" == "cloudflare" ]]; then
  cp nginx/notascore.http.conf nginx/notascore.conf
  docker compose --env-file .env.production up -d --build
  echo "Health: curl -fsS http://localhost/api/health"
  echo "Public: curl -fsS https://${DOMAIN}/api/health  (after DNS + Cloudflare proxy)"
elif [[ "$MODE" == "letsencrypt" ]]; then
  if [[ -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem ]] 2>/dev/null \
     || docker compose run --rm --entrypoint test certbot -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" 2>/dev/null; then
    cp nginx/notascore.tls.conf nginx/notascore.conf
    docker compose --env-file .env.production up -d --build
  else
    EMAIL="${EMAIL:?Set EMAIL=you@example.com}"
    cp nginx/notascore.http.conf nginx/notascore.conf
    docker compose --env-file .env.production up -d --build
    EMAIL="$EMAIL" DOMAINS="${DOMAIN} www.${DOMAIN}" ./deploy/init-tls.sh
  fi
  echo "Health: curl -fsS https://${DOMAIN}/api/health"
else
  echo "MODE must be cloudflare or letsencrypt" >&2
  exit 1
fi
