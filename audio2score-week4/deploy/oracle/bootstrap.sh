#!/usr/bin/env bash
# Bootstrap NotaScore on an Oracle Cloud Always Free Ubuntu VM.
#
# Modes:
#   cloudflare  — HTTP origin behind Cloudflare proxy (default, recommended)
#   letsencrypt — TLS on the VM with Let's Encrypt (grey-cloud DNS or direct A record)
#
# Usage (on a fresh VM):
#   curl -fsSL https://raw.githubusercontent.com/kozloved/notascore/cursor/oracle-deploy-setup-6c3d/audio2score-week4/deploy/oracle/bootstrap.sh | bash -s -- cloudflare
#
# Or after cloning:
#   MODE=cloudflare DOMAIN=notascore.com ./deploy/oracle/bootstrap.sh
set -euo pipefail

MODE="${1:-${MODE:-cloudflare}}"
DOMAIN="${DOMAIN:-notascore.com}"
EMAIL="${EMAIL:-}"
REPO_URL="${REPO_URL:-https://github.com/kozloved/notascore.git}"
BRANCH="${BRANCH:-cursor/oracle-deploy-setup-6c3d}"
APP_DIR="${APP_DIR:-$HOME/notascore/audio2score-week4}"

if [[ "$MODE" != "cloudflare" && "$MODE" != "letsencrypt" ]]; then
  echo "MODE must be 'cloudflare' or 'letsencrypt' (got: $MODE)" >&2
  exit 1
fi

if [[ "$MODE" == "letsencrypt" && -z "$EMAIL" ]]; then
  echo "Set EMAIL=you@example.com for letsencrypt mode." >&2
  exit 1
fi

if ! command -v docker &>/dev/null; then
  echo "Docker not found. Run: sudo ./deploy/oracle/install-docker.sh" >&2
  exit 1
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  REPO_ROOT="$(dirname "$(dirname "$APP_DIR")")"
  mkdir -p "$REPO_ROOT"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$REPO_ROOT"
fi

cd "$APP_DIR"
git fetch origin "$BRANCH" --depth 1
git checkout "$BRANCH"
git pull origin "$BRANCH" || true

if [[ ! -f .env.production ]]; then
  cp .env.production.example .env.production
fi

# Oracle does not use the Cloudflare Tunnel connector.
if grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=' .env.production; then
  sed -i 's/^CLOUDFLARE_TUNNEL_TOKEN=.*/CLOUDFLARE_TUNNEL_TOKEN=/' .env.production
fi

ensure_env() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" .env.production; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env.production
  else
    echo "${key}=${value}" >> .env.production
  fi
}

ensure_env NEXT_PUBLIC_API_URL "https://${DOMAIN}/api"
ensure_env CORS_ORIGIN "https://${DOMAIN},https://www.${DOMAIN}"

cp nginx/notascore.http.conf nginx/notascore.conf

echo "==> Building and starting stack (mode: $MODE)"
docker compose --env-file .env.production up -d --build

echo "==> Waiting for API health"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
curl -fsS http://localhost/api/health
echo

if [[ "$MODE" == "letsencrypt" ]]; then
  echo "==> Issuing Let's Encrypt certificates"
  EMAIL="$EMAIL" DOMAINS="${DOMAIN} www.${DOMAIN}" ./deploy/init-tls.sh
else
  cat <<EOF

==> Cloudflare mode
Point DNS at this VM's public IP (A records for @ and www, proxied/orange cloud).
Set SSL/TLS encryption mode to Full in Cloudflare.

Smoke test (after DNS propagates):
  curl -fsS https://${DOMAIN}/api/health
  BASE_URL=https://${DOMAIN}/api ./deploy/smoke-test.sh
EOF
fi

echo "==> Done"
