#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART_VERSION="${KUBE_PROMETHEUS_STACK_VERSION:-89.2.2}"

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update

VALUES=(
  -f "$ROOT/infra/helm/monitoring-values.yaml"
)

if [[ -f "$ROOT/infra/helm/telegram-values.yaml" ]]; then
  VALUES+=(-f "$ROOT/infra/helm/telegram-values.yaml")
fi

helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --version "$CHART_VERSION" \
  -n monitoring \
  --create-namespace \
  --wait \
  --timeout 10m \
  "${VALUES[@]}"
