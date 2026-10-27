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
  kubectl --context "${CTX}" -n "${NS}" create secret generic jump-ops-panel-secrets \
    --from-literal=JOP_PASSWORD_HICK="${JOP_PASSWORD_HICK}" \
    --dry-run=client -o yaml | kubectl --context "${CTX}" apply -f -
else
  echo "Hint: export JOP_PASSWORD_HICK=... before deploy to set JumpServer password secret."
fi

TMP="$(mktemp)"
sed "s|PLACEHOLDER_IMAGE|${IMAGE}|g" "${DIR}/deployment-dev.yaml" > "${TMP}"
kubectl --context "${CTX}" apply -f "${TMP}"
rm -f "${TMP}"

kubectl --context "${CTX}" -n "${NS}" rollout status deploy/jump-ops-panel --timeout=180s
kubectl --context "${CTX}" -n "${NS}" get pods,svc -l app=jump-ops-panel
echo "URL (dev NodePort): http://ai.wgine-dev.com:30765/"
