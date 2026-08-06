#!/usr/bin/env bash
# Run on the Oracle Ubuntu VM after Docker is installed and DNS points here.
set -euo pipefail

DOMAIN="${DOMAIN:-notascore.com}"
EMAIL="${EMAIL:?Set EMAIL=you@example.com}"
REPO_URL="${REPO_URL:-https://github.com/kozloved/notascore.git}"
APP_DIR="${APP_DIR:-$HOME/notascore/audio2score-week4}"

if [[ ! -d "$APP_DIR" ]]; then
  git clone "$REPO_URL" "$(dirname "$APP_DIR")/.."
  # clone creates ~/notascore if APP_DIR is ~/notascore/audio2score-week4
fi

if [[ ! -d "$APP_DIR" ]]; then
  git clone "$REPO_URL" "$HOME/notascore"
fi

cd "$APP_DIR"

if [[ ! -f .env.production ]]; then
  cp .env.production.example .env.production
fi

# HTTP-only nginx until certs exist
cp nginx/notascore.http.conf nginx/notascore.conf
docker compose up -d --build

echo "Waiting for nginx..."
sleep 5

docker compose run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" -d "www.$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos --no-eff-email \
  --non-interactive

# Restore TLS config from git
git checkout HEAD -- nginx/notascore.conf
docker compose up -d nginx

echo "Done. Check: https://$DOMAIN and https://$DOMAIN/api/health"
