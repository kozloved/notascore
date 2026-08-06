#!/usr/bin/env bash
# Issue Let's Encrypt certs then switch Nginx to the TLS config.
# Usage (on the VM, from audio2score-week4/):
#   EMAIL=you@example.com ./deploy/init-tls.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

EMAIL="${EMAIL:?Set EMAIL=you@example.com}"
DOMAINS="${DOMAINS:-notascore.com www.notascore.com}"

echo "==> Using HTTP nginx config for ACME"
cp nginx/notascore.http.conf nginx/notascore.conf
docker compose up -d nginx

DOMAIN_ARGS=()
for d in $DOMAINS; do
  DOMAIN_ARGS+=(-d "$d")
done

echo "==> Requesting certificates for: $DOMAINS"
docker compose run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  "${DOMAIN_ARGS[@]}" \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  --non-interactive

echo "==> Ensuring SSL helper files exist"
docker compose run --rm --entrypoint sh certbot -c '
  set -e
  if [ ! -f /etc/letsencrypt/options-ssl-nginx.conf ]; then
    wget -q -O /etc/letsencrypt/options-ssl-nginx.conf \
      https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf
  fi
  if [ ! -f /etc/letsencrypt/ssl-dhparams.pem ]; then
    openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048
  fi
'

echo "==> Switching to TLS nginx config"
cp nginx/notascore.tls.conf nginx/notascore.conf
docker compose up -d nginx
docker compose exec nginx nginx -t
docker compose exec nginx nginx -s reload

echo "==> Done. Visit https://notascore.com"
