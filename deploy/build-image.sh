#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${1:-dev-$(date +%Y%m%d%H%M%S)}"
REG="${JOP_IMAGE_REGISTRY:-registry.wgine-dev.com/ai-platform-public}"
IMAGE="${REG}/jump-ops-panel:${TAG}"

echo "Building ${IMAGE} (context: ${ROOT})"
docker build -f "${ROOT}/jump-ops-panel/deploy/Dockerfile" -t "${IMAGE}" "${ROOT}"

echo "${IMAGE}" > "${ROOT}/jump-ops-panel/deploy/.last-image"
echo "Built ${IMAGE}"
echo "Push: docker push ${IMAGE}"
