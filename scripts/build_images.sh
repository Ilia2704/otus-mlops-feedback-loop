#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
minikube image build -t titanic-model:demo -f apps/model_service/Dockerfile .
minikube image build -t titanic-drifter:demo -f demos/02_data_drift/drifter/Dockerfile .
minikube image build -t titanic-drift-checker:demo -f demos/02_data_drift/drift_checker/Dockerfile .
minikube image build -t titanic-retrainer:demo -f demos/03_feedback_loop/retrainer/Dockerfile .
minikube image build -t titanic-feedback-controller:demo -f demos/03_feedback_loop/controller/Dockerfile .
