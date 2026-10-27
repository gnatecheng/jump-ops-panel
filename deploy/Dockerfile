FROM python:3.12-slim-bookworm

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build context: parent dir `gnatecheng/` (see deploy/build-image.sh)
COPY mcp-jumpserver-gui-sucks /build/mcp-jumpserver-gui-sucks
COPY jump-ops-panel /build/jump-ops-panel

ARG PIP_INDEX_URL=https://maven.tuya-inc.top/repository/pypi-group/simple
ENV PIP_DEFAULT_TIMEOUT=120
RUN pip install --no-cache-dir \
    -i "${PIP_INDEX_URL}" \
    /build/mcp-jumpserver-gui-sucks \
    /build/jump-ops-panel

WORKDIR /build/jump-ops-panel

ENV JOP_HOST=0.0.0.0 \
    JOP_PORT=8765 \
    JOP_CONFIG=/config/profiles.yaml \
    JOP_DATA_DIR=/data \
    MCP_JUMPSERVER_GUI_SUCKS_LOG_LEVEL=WARNING

EXPOSE 8765

CMD ["jump-ops-panel"]
