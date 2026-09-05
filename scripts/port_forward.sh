#!/usr/bin/env bash
cat <<'EOF'
Open separate terminals:
  kubectl -n mlops-demo port-forward svc/titanic-model 8000:8000
  kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
  kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
  kubectl -n mlops-demo port-forward svc/mlflow 5000:5000
  kubectl -n mlops-demo port-forward svc/airflow 8080:8080
  kubectl -n mlops-demo port-forward svc/drifter 8001:8001
  kubectl -n mlops-demo port-forward svc/drift-checker 8002:8002
EOF
