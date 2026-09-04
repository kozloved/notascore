#!/usr/bin/env bash
# Build and push the YourMT3 worker for RunPod (linux/amd64 only).
# Usage, from this folder:
#   ./build-and-push.sh kozloved/notascore-yourmt3:0.2
set -euo pipefail
cd "$(dirname "$0")"
IMAGE="${1:-kozloved/notascore-yourmt3:0.2}"
echo "Building ${IMAGE} for linux/amd64"
docker buildx build --platform linux/amd64 -t "${IMAGE}" --push .
echo "Pushed ${IMAGE}"
echo "In RunPod, set the endpoint image to ${IMAGE} and redeploy."
