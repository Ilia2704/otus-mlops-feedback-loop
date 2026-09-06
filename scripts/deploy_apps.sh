#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

kubectl apply -f "$ROOT/infra/k8s/common/namespace.yaml"
kubectl apply -f "$ROOT/infra/k8s/common/demo-config.yaml"
kubectl apply -f "$ROOT/infra/k8s/common/model-pvc.yaml"
kubectl apply -f "$ROOT/infra/k8s/common/minio.yaml"
kubectl -n mlops-demo rollout status deployment/minio --timeout=5m
kubectl -n mlops-demo create configmap reference-dataset \
  --from-file=titanic_train.csv="$ROOT/data/titanic_train.csv" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$ROOT/infra/k8s/common/minio-init.yaml"
kubectl -n mlops-demo wait --for=condition=complete job/minio-init --timeout=5m
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

# Monitoring CRs used to live in mlops-demo.  Keep upgrades idempotent and
# prevent duplicate Grafana dashboards / Prometheus rules during the move.
kubectl -n mlops-demo delete servicemonitor mlops-demo --ignore-not-found
kubectl -n mlops-demo delete configmap titanic-dashboard --ignore-not-found
kubectl -n mlops-demo delete prometheusrule titanic-demo-alerts --ignore-not-found

for deployment in minio mlflow titanic-model drifter drift-checker airflow retrainer feedback-controller; do
  kubectl -n mlops-demo rollout status "deployment/$deployment" --timeout=5m
done

kubectl -n mlops-demo get pods,svc
