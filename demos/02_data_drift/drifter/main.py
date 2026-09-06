from __future__ import annotations

import io
import os
import threading
import time

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from prometheus_client import Counter, Gauge
from starlette_exporter import PrometheusMiddleware, handle_metrics

from shared.drift import drift_dataframe, row_payload
from shared.object_store import read_csv

MODEL_URL = os.getenv("MODEL_URL", "http://titanic-model:8000")
REQUEST_INTERVAL_SECONDS = float(os.getenv("REQUEST_INTERVAL_SECONDS", "1"))
DRIFT_STEP_PER_REQUEST = float(os.getenv("DRIFT_STEP_PER_REQUEST", "0.002"))
DRIFT_MAX = float(os.getenv("DRIFT_MAX", "0.95"))
INVALID_RATE = float(os.getenv("INVALID_RATE", "0.08"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "mlops-data")
REFERENCE_DATASET_KEY = os.getenv("REFERENCE_DATASET_KEY", "reference/titanic_train.csv")

app = FastAPI(title="Titanic drifter")
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", handle_metrics)

STRENGTH = Gauge("titanic_demo_drift_strength", "Current synthetic drift strength")
TRAFFIC = Counter("titanic_demo_generated_requests", "Generated prediction requests", ["status"])

_base = read_csv(MINIO_BUCKET, REFERENCE_DATASET_KEY)
_lock = threading.Lock()
_requests_sent = 0
_rng = np.random.default_rng(42)


def current_strength() -> float:
    with _lock:
        value = min(DRIFT_MAX, _requests_sent * DRIFT_STEP_PER_REQUEST)
    STRENGTH.set(value)
    return value


def _one_request() -> None:
    global _requests_sent
    strength = current_strength()
    idx = int(_rng.integers(0, len(_base)))
    row = drift_dataframe(_base.iloc[[idx]], strength, seed=int(_rng.integers(1, 2**31))).iloc[0]
    invalid = bool(_rng.random() < INVALID_RATE)
    try:
        response = requests.post(f"{MODEL_URL}/predict", json=row_payload(row, invalid), timeout=5)
        TRAFFIC.labels(status=str(response.status_code)).inc()
    except requests.RequestException:
        TRAFFIC.labels(status="network_error").inc()
    finally:
        with _lock:
            _requests_sent += 1


def _loop() -> None:
    while True:
        _one_request()
        time.sleep(REQUEST_INTERVAL_SECONDS)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=_loop, daemon=True).start()


@app.get("/")
def health() -> dict:
    return {"status": "ok", "drift_strength": current_strength(), "requests_sent": _requests_sent}


@app.get("/data")
def data(rows: int = Query(default=400, ge=20, le=5000)):
    strength = current_strength()
    sampled = _base.sample(rows, replace=True, random_state=int(_rng.integers(1, 2**31)))
    current = drift_dataframe(sampled, strength, seed=int(_rng.integers(1, 2**31)))
    return StreamingResponse(io.StringIO(current.to_csv(index=False)), media_type="text/csv")


@app.post("/reset")
def reset() -> dict:
    global _requests_sent
    with _lock:
        _requests_sent = 0
    STRENGTH.set(0)
    return {"status": "reset"}
