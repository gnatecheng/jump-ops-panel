#!/usr/bin/env bash
set -euo pipefail

CTX="${KUBE_CONTEXT:-dev}"
NS=chengyt
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${DIR}/../.." && pwd)"
IMAGE="${1:-}"

if [[ -z "${IMAGE}" ]]; then
  if [[ -f "${ROOT}/jump-ops-panel/deploy/.last-image" ]]; then
    IMAGE="$(cat "${ROOT}/jump-ops-panel/deploy/.last-image")"
  else
    echo "Usage: $0 <full-image-ref>" >&2
    exit 1
  fi
fi

if [[ -n "${JOP_PASSWORD_HICK:-}" ]]; then
  "${DIR}/update-jms-password.sh"
else
  if ! kubectl --context "${CTX}" -n "${NS}" get secret jump-ops-panel-secrets &>/dev/null; then
    echo "ERROR: Secret jump-ops-panel-secrets 不存在。请先运行:" >&2
    echo "  JOP_PASSWORD_HICK='...' ${DIR}/update-jms-password.sh" >&2
    exit 1
  fi
  echo "Secret 未改动（未设置 JOP_PASSWORD_HICK）。仅更新 Deployment/ConfigMap。"
fi

TMP="$(mktemp)"
sed "s|PLACEHOLDER_IMAGE|${IMAGE}|g" "${DIR}/deployment-dev.yaml" > "${TMP}"
kubectl --context "${CTX}" apply -f "${TMP}"
rm -f "${TMP}"

kubectl --context "${CTX}" -n "${NS}" rollout status deploy/jump-ops-panel --timeout=180s
kubectl --context "${CTX}" -n "${NS}" get pods,svc -l app=jump-ops-panel
echo "URL (dev NodePort): http://ai.wgine-dev.com:30765/"
