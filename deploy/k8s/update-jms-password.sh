#!/usr/bin/env bash
# 更新 JumpServer 用户 hick 的密码（写入 Secret，并重启 Pod 使环境变量生效）
set -euo pipefail

CTX="${KUBE_CONTEXT:-dev}"
NS="${JOP_NAMESPACE:-chengyt}"
SECRET_NAME=jump-ops-panel-secrets
KEY=JOP_PASSWORD_HICK

if [[ -z "${JOP_PASSWORD_HICK:-}" ]]; then
  echo "用法: export JOP_PASSWORD_HICK='JumpServer上hick的密码'" >&2
  echo "      $0" >&2
  echo "" >&2
  echo "或一行: JOP_PASSWORD_HICK='...' $0" >&2
  exit 1
fi

kubectl --context "${CTX}" -n "${NS}" create secret generic "${SECRET_NAME}" \
  --from-literal="${KEY}=${JOP_PASSWORD_HICK}" \
  --dry-run=client -o yaml | kubectl --context "${CTX}" apply -f -

kubectl --context "${CTX}" -n "${NS}" rollout restart deployment/jump-ops-panel
kubectl --context "${CTX}" -n "${NS}" rollout status deployment/jump-ops-panel --timeout=180s

echo "Secret ${SECRET_NAME} 已更新，Pod 已重启。"
echo "验证长度（勿泄露明文）:"
kubectl --context "${CTX}" -n "${NS}" get secret "${SECRET_NAME}" \
  -o jsonpath='{.data.'"${KEY}"'}' | base64 -d | wc -c
