#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MCP_DIR="${ROOT}/mcp-jumpserver-gui-sucks"
PANEL_DIR="${ROOT}/jump-ops-panel"
TAG="${1:-dev-$(date +%Y%m%d%H%M%S)}"
REG="${JOP_IMAGE_REGISTRY:-registry.wgine-dev.com/ai-platform-public}"
IMAGE="${REG}/jump-ops-panel:${TAG}"

if [[ ! -d "${MCP_DIR}/src/mcp_jumpserver_gui_sucks" ]]; then
  echo "Missing local fork: ${MCP_DIR}" >&2
  echo "Build context must include sibling mcp-jumpserver-gui-sucks (your modified fork)." >&2
  exit 1
fi

if ! grep -q "_sync_session_api_headers" "${MCP_DIR}/src/mcp_jumpserver_gui_sucks/cli_login.py"; then
  echo "WARN: mcp-jumpserver-gui-sucks does not contain CSRF patch (_sync_session_api_headers)." >&2
fi

MCP_GIT_SHA="$(git -C "${MCP_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
PANEL_GIT_SHA="$(git -C "${PANEL_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"

echo "Building ${IMAGE}"
echo "  context: ${ROOT}"
echo "  mcp-jumpserver-gui-sucks @ ${MCP_GIT_SHA}"
echo "  jump-ops-panel @ ${PANEL_GIT_SHA}"

docker build -f "${PANEL_DIR}/deploy/Dockerfile" \
  --build-arg "MCP_GIT_SHA=${MCP_GIT_SHA}" \
  --build-arg "PANEL_GIT_SHA=${PANEL_GIT_SHA}" \
  -t "${IMAGE}" "${ROOT}"

echo "${IMAGE}" > "${PANEL_DIR}/deploy/.last-image"
echo "Built ${IMAGE}"
echo "Push: docker push ${IMAGE}"
