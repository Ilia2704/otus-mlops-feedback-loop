from __future__ import annotations

import os
import threading
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram
from starlette_exporter import PrometheusMiddleware, handle_metrics

from shared.titanic_model import (
    load_model,
    predict_one,
    predict_probability_one,
    save_model,
    train_model,
)

DATA_PATH = Path(os.getenv("DATA_PATH", "/app/data/titanic_train.csv"))
MODEL_PATH = Path(os.getenv("MODEL_PATH", "/models/model.joblib"))

app = FastAPI(title="Titanic survival service")
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", handle_metrics)

PREDICTIONS = Counter("titanic_predictions", "Predictions", ["prediction"])
LABELED = Counter("titanic_labeled_predictions", "Predictions with known target")
CORRECT = Counter("titanic_correct_predictions", "Correct predictions with known target")
UNKNOWN = Counter("titanic_unknown_category", "Unknown/drifted categorical values", ["feature"])
RELOADS = Counter("titanic_model_reloads", "Model reloads")
MODEL_MTIME = Gauge("titanic_model_mtime_seconds", "mtime of the loaded model")
INPUT_CATEGORY = Counter("titanic_input_category", "Observed categorical inputs", ["feature", "value"])
AGE = Histogram(
    "titanic_input_age_years",
    "Passenger age distribution",
    buckets=[5, 12, 18, 25, 35, 50, 65, 80, 100],
)
FARE = Histogram(
    "titanic_input_fare",
    "Passenger fare distribution",
    buckets=[5, 10, 20, 40, 80, 150, 300, 500, 800],
)
FAMILY_SIZE = Histogram(
    "titanic_input_family_size",
    "Passenger family size distribution",
    buckets=[1, 2, 3, 4, 5, 6, 8, 10],
)
PROBABILITY = Histogram(
    "titanic_survival_probability",
    "Predicted survival probability",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
)

_lock = threading.Lock()
_model = None
_model_mtime = 0.0


class Passenger(BaseModel):
    Pclass: int = Field(ge=1, le=3)
    Name: str = "Passenger"
    Sex: str
    Age: float | None = Field(default=None, ge=0, le=120)
    SibSp: int = Field(default=0, ge=0)
    Parch: int = Field(default=0, ge=0)
    Ticket: str = "DEMO"
    Fare: float = Field(default=0.0, ge=0)
    Cabin: str | None = None
    Embarked: str | None = None
    actual_survived: int | None = Field(default=None, ge=0, le=1)


def _ensure_model() -> None:
    global _model, _model_mtime
    with _lock:
        if not MODEL_PATH.exists():
            save_model(train_model(pd.read_csv(DATA_PATH)), MODEL_PATH)
        mtime = MODEL_PATH.stat().st_mtime
        if _model is None or mtime != _model_mtime:
            _model = load_model(MODEL_PATH)
            _model_mtime = mtime
            MODEL_MTIME.set(mtime)
            RELOADS.inc()


@app.on_event("startup")
def startup() -> None:
    _ensure_model()


@app.get("/")
def health() -> dict:
    _ensure_model()
    return {"status": "ok", "model_mtime": _model_mtime}


@app.post("/predict")
def predict(passenger: Passenger) -> dict:
    _ensure_model()
    payload = passenger.model_dump()
    try:
        prediction = predict_one(_model, payload)
        probability = predict_probability_one(_model, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if "_drift" in passenger.Sex:
        UNKNOWN.labels(feature="Sex").inc()
    if passenger.Embarked and "_drift" in passenger.Embarked:
        UNKNOWN.labels(feature="Embarked").inc()

    INPUT_CATEGORY.labels(feature="Pclass", value=str(passenger.Pclass)).inc()
    INPUT_CATEGORY.labels(feature="Sex", value=passenger.Sex).inc()
    INPUT_CATEGORY.labels(feature="Embarked", value=passenger.Embarked or "unknown").inc()
    if passenger.Age is not None:
        AGE.observe(passenger.Age)
    FARE.observe(passenger.Fare)
    FAMILY_SIZE.observe(passenger.SibSp + passenger.Parch + 1)
    PROBABILITY.observe(probability)

    PREDICTIONS.labels(prediction=str(prediction)).inc()
    if passenger.actual_survived is not None:
        LABELED.inc()
        if prediction == passenger.actual_survived:
            CORRECT.inc()

    return {
        "survived": prediction,
        "survival_probability": round(probability, 6),
        "model_mtime": _model_mtime,
    }
