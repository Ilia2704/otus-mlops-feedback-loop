#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
kubectl -n mlops-demo scale deployment/titanic-model deployment/retrainer --replicas=0
kubectl -n mlops-demo delete pvc model-pvc --ignore-not-found --wait=true
kubectl -n mlops-demo apply -f "$ROOT/infra/k8s/common/model-pvc.yaml"
kubectl -n mlops-demo scale deployment/titanic-model deployment/retrainer --replicas=1
kubectl -n mlops-demo rollout restart deployment/drifter deployment/feedback-controller
echo "Demo reset: drift starts from zero and baseline model will be recreated."
