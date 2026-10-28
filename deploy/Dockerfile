FROM python:3.12-slim-bookworm

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build context MUST be the `gnatecheng/` directory containing both sibling repos
# (see deploy/build-image.sh). Never install mcp-jumpserver-gui-sucks from PyPI here.
COPY mcp-jumpserver-gui-sucks /build/mcp-jumpserver-gui-sucks
COPY jump-ops-panel /build/jump-ops-panel

ARG PIP_INDEX_URL=https://maven.tuya-inc.top/repository/pypi-group/simple
ARG MCP_GIT_SHA=unknown
ARG PANEL_GIT_SHA=unknown
ENV PIP_DEFAULT_TIMEOUT=120

RUN printf '%s\n' \
    "mcp-jumpserver-gui-sucks=${MCP_GIT_SHA}" \
    "jump-ops-panel=${PANEL_GIT_SHA}" \
    > /etc/jop-build-info

# 1) Local fork (CSRF fix, terminal-shell quiet, etc.) — force, no PyPI substitute
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" --force-reinstall \
    /build/mcp-jumpserver-gui-sucks

# 2) Panel wheel without re-resolving mcp from the index
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" --no-deps \
    /build/jump-ops-panel \
 && pip install --no-cache-dir -i "${PIP_INDEX_URL}" \
    "apscheduler>=3.10.4" \
    "fastapi>=0.115.0" \
    "jinja2>=3.1.4" \
    "pydantic>=2.10.0" \
    "pydantic-settings>=2.6.0" \
    "pyyaml>=6.0.2" \
    "uvicorn[standard]>=0.32.0"

# Sanity: bundled library must be the workspace fork, not a stale PyPI build
RUN python -c "import importlib.metadata as m; import mcp_jumpserver_gui_sucks.cli_login as cl; \
v=m.version('mcp-jumpserver-gui-sucks'); \
assert hasattr(cl.JumpServerCLILogin, '_sync_session_api_headers'), 'missing CSRF sync patch'; \
print('mcp-jumpserver-gui-sucks', v, 'ok')"

WORKDIR /build/jump-ops-panel

ENV JOP_HOST=0.0.0.0 \
    JOP_PORT=8765 \
    JOP_CONFIG=/config/profiles.yaml \
    JOP_DATA_DIR=/data \
    JOP_PROJECT_ROOT=/build/jump-ops-panel \
    MCP_JUMPSERVER_GUI_SUCKS_LOG_LEVEL=WARNING

LABEL org.opencontainers.image.title="jump-ops-panel" \
      org.opencontainers.image.vendor="gnatecheng" \
      org.opencontainers.image.revision.mcp="${MCP_GIT_SHA}" \
      org.opencontainers.image.revision.panel="${PANEL_GIT_SHA}"

EXPOSE 8765

CMD ["jump-ops-panel"]
