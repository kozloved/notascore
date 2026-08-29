#!/usr/bin/env bash
# Ubuntu 22.04/24.04 VPS bootstrap: Docker, Compose plugin, 2G swap, SSH-only firewall.
# Run once as root:  sudo bash audio2score-week4/deploy/vps-setup.sh
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git ufw

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

systemctl enable --now docker

# Compose v2 plugin is included with get.docker.com. Fail clearly if not.
docker compose version >/dev/null

for user in root ubuntu; do
  if id "$user" >/dev/null 2>&1; then
    usermod -aG docker "$user" || true
  fi
done

# 4 GB CX22 needs swap for Basic Pitch + two backend containers.
if ! swapon --show | grep -q .; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile || true
  if ! grep -q '^/swapfile ' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
fi

# Tunnel-only: do not expose HTTP/HTTPS on the public IP.
ufw allow OpenSSH
ufw --force enable

echo
echo "Docker:  $(docker --version)"
echo "Compose: $(docker compose version)"
echo "Memory:"
free -h
echo
echo "Next: cd audio2score-week4 && cp .env.production.example .env.production"
echo "      # set CLOUDFLARE_TUNNEL_TOKEN, then ./deploy/start-local-tunnel.sh"
