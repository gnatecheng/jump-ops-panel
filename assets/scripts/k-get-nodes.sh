#!/usr/bin/env bash
set -euo pipefail
if command -v k >/dev/null 2>&1; then
  k get nodes
elif command -v kubectl >/dev/null 2>&1; then
  kubectl get nodes
else
  echo "kubectl/k not found in PATH" >&2
  exit 127
fi
