#!/usr/bin/env bash
# Optional 2 GiB swap for small Oracle VMs running Basic Pitch.
# Usage: sudo ./deploy/oracle/setup-swap.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

SWAP_FILE="${SWAP_FILE:-/swapfile}"
SWAP_GB="${SWAP_GB:-2}"

if swapon --show | grep -q "$SWAP_FILE"; then
  echo "Swap already active: $SWAP_FILE"
  exit 0
fi

fallocate -l "${SWAP_GB}G" "$SWAP_FILE" || dd if=/dev/zero of="$SWAP_FILE" bs=1M count=$((SWAP_GB * 1024))
chmod 600 "$SWAP_FILE"
mkswap "$SWAP_FILE"
swapon "$SWAP_FILE"

if ! grep -q "$SWAP_FILE" /etc/fstab; then
  echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
fi

echo "Swap enabled:"
swapon --show
