#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

kubectl apply -f "$ROOT/infra/k8s/common/namespace.yaml"
kubectl apply -f "$ROOT/infra/k8s/common/demo-config.yaml"
kubectl apply -f "$ROOT/infra/k8s/common/model-pvc.yaml"
kubectl apply -f "$ROOT/infra/k8s/common/mlflow.yaml"
kubectl apply -f "$ROOT/infra/k8s/01_monitoring/model-service.yaml"
kubectl apply -f "$ROOT/infra/k8s/02_data_drift/drifter.yaml"
kubectl apply -f "$ROOT/infra/k8s/02_data_drift/drift-checker.yaml"
kubectl -n mlops-demo create configmap airflow-dag \
  --from-file=drift_detection.py="$ROOT/demos/02_data_drift/airflow/drift_detection.py" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$ROOT/infra/k8s/02_data_drift/airflow.yaml"
kubectl apply -f "$ROOT/infra/k8s/03_feedback_loop/retrainer.yaml"
kubectl apply -f "$ROOT/infra/k8s/03_feedback_loop/controller.yaml"
kubectl apply -f "$ROOT/infra/k8s/01_monitoring/servicemonitor.yaml"
kubectl apply -f "$ROOT/infra/k8s/01_monitoring/grafana-dashboard.yaml"
kubectl apply -f "$ROOT/infra/k8s/04_alerting/prometheus-rules.yaml"

for deployment in mlflow titanic-model drifter drift-checker airflow retrainer feedback-controller; do
  kubectl -n mlops-demo rollout status "deployment/$deployment" --timeout=5m
done

kubectl -n mlops-demo get pods,svc
