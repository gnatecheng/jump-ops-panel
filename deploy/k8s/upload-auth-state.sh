#!/usr/bin/env bash
# 将本机 CLI 登录后的 auth-state 同步到集群（绕过 Pod 内验证码登录）
set -euo pipefail

CTX="${KUBE_CONTEXT:-dev}"
NS="${JOP_NAMESPACE:-chengyt}"
PROFILE_ID="${JOP_PROFILE_ID:-ai-speaker-jms}"
LOCAL="${JOP_AUTH_STATE_FILE:-${HOME}/.local/state/mcp-jumpserver-gui-sucks/auth-state.json}"
SECRET=jump-ops-panel-auth-state

if [[ ! -f "${LOCAL}" ]]; then
  echo "找不到 ${LOCAL}，请先在本地执行:" >&2
  echo "  mcp-jumpserver-gui-sucks login --base-url ... --username hick" >&2
  exit 1
fi

kubectl --context "${CTX}" -n "${NS}" create secret generic "${SECRET}" \
  --from-file=auth-state.json="${LOCAL}" \
  --dry-run=client -o yaml | kubectl --context "${CTX}" apply -f -

kubectl --context "${CTX}" -n "${NS}" rollout restart deployment/jump-ops-panel
kubectl --context "${CTX}" -n "${NS}" rollout status deployment/jump-ops-panel --timeout=180s

echo "已上传 auth-state 并重启 Pod（挂载到 /data/state/${PROFILE_ID}/auth-state.json）"
