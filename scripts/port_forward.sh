#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${TMPDIR:-/tmp}/titanic-mlops-port-forwards"
ACTION="${1:-start}"

# name|namespace|service|local-port|service-port
FORWARDS=(
  "titanic-model|mlops-demo|titanic-model|8000|8000"
  "grafana|monitoring|monitoring-grafana|3000|80"
  "prometheus|monitoring|monitoring-kube-prometheus-prometheus|9090|9090"
  "alertmanager|monitoring|monitoring-kube-prometheus-alertmanager|9093|9093"
  "minio|mlops-demo|minio|9001|9001"
  "mlflow|mlops-demo|mlflow|5000|5000"
  "airflow|mlops-demo|airflow|8080|8080"
  "drifter|mlops-demo|drifter|8001|8001"
  "drift-checker|mlops-demo|drift-checker|8002|8002"
  "retrainer|mlops-demo|retrainer|8004|8004"
)

mkdir -p "$RUNTIME_DIR"

pid_is_our_port_forward() {
  local pid="$1"
  local service="$2"
  local command
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command" == *"kubectl"* && "$command" == *"port-forward svc/$service"* ]]
}

local_port_is_busy() {
  command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

start_forward() {
  local name="$1" namespace="$2" service="$3" local_port="$4" service_port="$5"
  local pid_file="$RUNTIME_DIR/$name.pid"
  local log_file="$RUNTIME_DIR/$name.log"
  local pid

  if ! kubectl -n "$namespace" get service "$service" >/dev/null 2>&1; then
    printf 'SKIP %-14s service %s/%s is not deployed\n' "$name" "$namespace" "$service"
    return
  fi

  if [[ -f "$pid_file" ]]; then
    pid="$(<"$pid_file")"
    if kill -0 "$pid" 2>/dev/null && pid_is_our_port_forward "$pid" "$service"; then
      printf 'READY %-13s http://127.0.0.1:%s (pid %s)\n' "$name" "$local_port" "$pid"
      return
    fi
    rm -f "$pid_file"
  fi

  if local_port_is_busy "$local_port"; then
    printf 'SKIP %-14s local port %s is already in use (not managed by this script)\n' \
      "$name" "$local_port"
    return
  fi

  nohup kubectl -n "$namespace" port-forward "svc/$service" "$local_port:$service_port" \
    >"$log_file" 2>&1 &
  pid=$!
  echo "$pid" >"$pid_file"
  sleep 0.3

  if ! kill -0 "$pid" 2>/dev/null; then
    printf 'ERROR %-13s did not start; inspect %s\n' "$name" "$log_file" >&2
    rm -f "$pid_file"
    return
  fi
  printf 'START %-13s http://127.0.0.1:%s (pid %s)\n' "$name" "$local_port" "$pid"
}

status_forward() {
  local name="$1" _namespace="$2" service="$3" local_port="$4" _service_port="$5"
  local pid_file="$RUNTIME_DIR/$name.pid"
  local pid

  if [[ -f "$pid_file" ]]; then
    pid="$(<"$pid_file")"
    if kill -0 "$pid" 2>/dev/null && pid_is_our_port_forward "$pid" "$service"; then
      printf 'READY %-13s http://127.0.0.1:%s (pid %s)\n' "$name" "$local_port" "$pid"
      return
    fi
  fi
  if local_port_is_busy "$local_port"; then
    printf 'EXTERNAL %-10s http://127.0.0.1:%s (not managed by this script)\n' \
      "$name" "$local_port"
    return
  fi
  printf 'STOPPED %-11s\n' "$name"
}

stop_forward() {
  local name="$1" _namespace="$2" service="$3" _local_port="$4" _service_port="$5"
  local pid_file="$RUNTIME_DIR/$name.pid"
  local pid

  [[ -f "$pid_file" ]] || return
  pid="$(<"$pid_file")"
  if kill -0 "$pid" 2>/dev/null && pid_is_our_port_forward "$pid" "$service"; then
    kill "$pid"
    printf 'STOP %-14s pid %s\n' "$name" "$pid"
  fi
  rm -f "$pid_file"
}

case "$ACTION" in
  start|status|stop)
    ;;
  *)
    echo "Usage: $0 {start|status|stop}" >&2
    exit 2
    ;;
esac

for forward in "${FORWARDS[@]}"; do
  IFS='|' read -r name namespace service local_port service_port <<<"$forward"
  case "$ACTION" in
    start) start_forward "$name" "$namespace" "$service" "$local_port" "$service_port" ;;
    status) status_forward "$name" "$namespace" "$service" "$local_port" "$service_port" ;;
    stop) stop_forward "$name" "$namespace" "$service" "$local_port" "$service_port" ;;
  esac
done
