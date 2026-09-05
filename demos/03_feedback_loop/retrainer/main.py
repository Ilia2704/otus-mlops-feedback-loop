from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path

import mlflow
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from starlette_exporter import PrometheusMiddleware, handle_metrics

from shared.titanic_model import MODEL_FEATURES, clean_features, save_model, train_model

MODEL_PATH = Path(os.getenv("MODEL_PATH", "/models/model.joblib"))
DRIFTER_URL = os.getenv("DRIFTER_URL", "http://drifter:8001")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
RETRAIN_ROWS = int(os.getenv("RETRAIN_ROWS", "800"))

app = FastAPI(title="Titanic retrainer")
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", handle_metrics)

RUNS = Counter("titanic_retraining_runs", "Retraining runs", ["result"])
LAST_ACCURACY = Gauge("titanic_retraining_accuracy", "Validation accuracy of the last retrain")
LAST_ROC_AUC = Gauge("titanic_retraining_roc_auc", "Validation ROC-AUC of the last retrain")


def retrain_once() -> dict:
    response = requests.get(f"{DRIFTER_URL}/data", params={"rows": RETRAIN_ROWS}, timeout=30)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    train_df, test_df = train_test_split(
        df,
        test_size=0.25,
        stratify=df["Survived"],
        random_state=42,
    )
    model = train_model(train_df)
    x_test = clean_features(test_df)
    y_test = test_df["Survived"].astype(int)
    prediction = model.predict(x_test)
    probability = model.predict_proba(x_test)[:, 1]
    accuracy = float(accuracy_score(y_test, prediction))
    roc_auc = float(roc_auc_score(y_test, probability))

    save_model(model, MODEL_PATH)
    LAST_ACCURACY.set(accuracy)
    LAST_ROC_AUC.set(roc_auc)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("titanic-retraining")
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "model.joblib"
        shutil.copy2(MODEL_PATH, artifact)
        with mlflow.start_run() as run:
            mlflow.log_param("rows", len(df))
            mlflow.log_param("model", "LogisticRegression")
            mlflow.log_param("features", ",".join(MODEL_FEATURES))
            mlflow.log_metric("validation_accuracy", accuracy)
            mlflow.log_metric("validation_roc_auc", roc_auc)
            mlflow.log_metric("survival_rate", float(df["Survived"].mean()))
            mlflow.log_artifact(str(artifact), "model")
            run_id = run.info.run_id

    RUNS.labels(result="success").inc()
    return {
        "status": "retrained",
        "validation_accuracy": accuracy,
        "validation_roc_auc": roc_auc,
        "mlflow_run_id": run_id,
    }


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


@app.post("/retrain")
def retrain() -> dict:
    try:
        return retrain_once()
    except Exception as exc:
        RUNS.labels(result="error").inc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
