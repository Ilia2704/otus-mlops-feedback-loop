from __future__ import annotations

import math
import os
import threading
import time

import requests
from fastapi import FastAPI
from prometheus_client import Counter, Gauge
from starlette_exporter import PrometheusMiddleware, handle_metrics

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://monitoring-kube-prometheus-prometheus.monitoring.svc:9090")
RETRAINER_URL = os.getenv("RETRAINER_URL", "http://retrainer:8004")
CHECK_INTERVAL_SECONDS = float(os.getenv("CHECK_INTERVAL_SECONDS", "15"))
ACCURACY_THRESHOLD = float(os.getenv("ACCURACY_THRESHOLD", "0.78"))
ACCURACY_WINDOW = os.getenv("ACCURACY_WINDOW", "2m")
BAD_CHECKS_BEFORE_RETRAIN = int(os.getenv("BAD_CHECKS_BEFORE_RETRAIN", "2"))
RETRAIN_COOLDOWN_SECONDS = float(os.getenv("RETRAIN_COOLDOWN_SECONDS", "120"))

app = FastAPI(title="Titanic feedback controller")
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", handle_metrics)

ACCURACY = Gauge("titanic_controller_observed_accuracy", "Accuracy observed from Prometheus")
BAD_CHECKS = Gauge("titanic_controller_bad_checks", "Consecutive bad accuracy checks")
RETRAINS = Counter("titanic_controller_retrain_triggers", "Automatic retrain triggers", ["result"])

_state = {"bad": 0, "last_retrain": 0.0, "last_accuracy": None}


def query_accuracy() -> float | None:
    query = (
        f"sum(rate(titanic_correct_predictions_total[{ACCURACY_WINDOW}])) / "
        f"clamp_min(sum(rate(titanic_labeled_predictions_total[{ACCURACY_WINDOW}])), 0.001)"
    )
    r = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=10)
    r.raise_for_status()
    result = r.json().get("data", {}).get("result", [])
    if not result:
        return None
    value = float(result[0]["value"][1])
    return value if math.isfinite(value) else None


def check_once() -> None:
    accuracy = query_accuracy()
    if accuracy is None:
        return
    _state["last_accuracy"] = accuracy
    ACCURACY.set(accuracy)

    _state["bad"] = _state["bad"] + 1 if accuracy < ACCURACY_THRESHOLD else 0
    BAD_CHECKS.set(_state["bad"])

    cooldown_over = time.time() - _state["last_retrain"] >= RETRAIN_COOLDOWN_SECONDS
    if _state["bad"] >= BAD_CHECKS_BEFORE_RETRAIN and cooldown_over:
        try:
            r = requests.post(f"{RETRAINER_URL}/retrain", timeout=300)
            r.raise_for_status()
            _state["last_retrain"] = time.time()
            _state["bad"] = 0
            BAD_CHECKS.set(0)
            RETRAINS.labels(result="success").inc()
        except requests.RequestException:
            RETRAINS.labels(result="error").inc()


def _loop() -> None:
    while True:
        try:
            check_once()
        except requests.RequestException:
            pass
        time.sleep(CHECK_INTERVAL_SECONDS)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=_loop, daemon=True).start()


@app.get("/")
def health() -> dict:
    return {"status": "ok", **_state}
