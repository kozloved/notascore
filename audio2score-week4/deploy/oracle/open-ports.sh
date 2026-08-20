#!/usr/bin/env bash
# Open HTTP/HTTPS on the VM firewall (UFW).
# You must ALSO allow TCP 80 and 443 in the Oracle Cloud security list / NSG.
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

apt-get update
apt-get install -y ufw

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status

cat <<'EOF'

Oracle Cloud: open the same ports in the console
  Networking → Virtual cloud networks → your VCN → Security Lists
  Ingress rules: TCP 80 and 443 from 0.0.0.0/0 (or Cloudflare IP ranges only)

With Cloudflare proxy (orange cloud), HTTP on port 80 is enough for the simple path.
EOF
