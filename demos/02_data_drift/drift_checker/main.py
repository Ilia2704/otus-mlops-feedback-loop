from __future__ import annotations

import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import mlflow
import pandas as pd
import requests
from evidently import ColumnMapping
from evidently.metric_preset import DataDriftPreset
from evidently.report import Report
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge
from starlette_exporter import PrometheusMiddleware, handle_metrics

from shared.object_store import put_text, read_csv

DRIFTER_URL = os.getenv("DRIFTER_URL", "http://drifter:8001")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
DRIFT_ROWS = int(os.getenv("DRIFT_ROWS", "400"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "mlops-data")
REFERENCE_DATASET_KEY = os.getenv("REFERENCE_DATASET_KEY", "reference/titanic_train.csv")
CURRENT_DATASET_PREFIX = os.getenv("CURRENT_DATASET_PREFIX", "current")

RAW_FEATURES = ["Pclass", "Sex", "Age", "SibSp", "Parch", "Fare", "Embarked"]
NUMERIC_FEATURES = ["Age", "SibSp", "Parch", "Fare"]
CATEGORICAL_FEATURES = ["Pclass", "Sex", "Embarked"]

app = FastAPI(title="Titanic Evidently drift checker")
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", handle_metrics)

DRIFT_DETECTED = Gauge("titanic_drift_detected", "1 when Evidently reports dataset drift")
DRIFT_SHARE = Gauge("titanic_drift_share", "Share of drifted model input features")
FEATURE_DRIFT_SCORE = Gauge("titanic_feature_drift_score", "Evidently drift score by feature", ["feature"])
CHECKS = Counter("titanic_drift_checks", "Drift checks", ["result"])


def extract_drift_result(report_dict: dict) -> dict:
    for metric in report_dict.get("metrics", []):
        result = metric.get("result", {})
        required = {"dataset_drift", "share_of_drifted_columns", "drift_by_columns"}
        if isinstance(result, dict) and required <= result.keys():
            return result
    raise ValueError("Evidently drift summary not found")


def run_check() -> dict:
    reference = read_csv(MINIO_BUCKET, REFERENCE_DATASET_KEY)
    response = requests.get(f"{DRIFTER_URL}/data", params={"rows": DRIFT_ROWS}, timeout=30)
    response.raise_for_status()
    current = pd.read_csv(io.StringIO(response.text))
    current_key = (
        f"{CURRENT_DATASET_PREFIX}/drift-check-"
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex}.csv"
    )
    current_dataset_uri = put_text(
        MINIO_BUCKET,
        current_key,
        current.to_csv(index=False),
        content_type="text/csv",
    )

    for frame in (reference, current):
        frame["Pclass"] = frame["Pclass"].astype(str)
        frame["Sex"] = frame["Sex"].fillna("unknown").astype(str)
        frame["Embarked"] = frame["Embarked"].fillna("unknown").astype(str)

    mapping = ColumnMapping()
    mapping.numerical_features = NUMERIC_FEATURES
    mapping.categorical_features = CATEGORICAL_FEATURES

    report = Report(metrics=[DataDriftPreset()])
    report.run(
        reference_data=reference[RAW_FEATURES],
        current_data=current[RAW_FEATURES],
        column_mapping=mapping,
    )
    report_dict = report.as_dict()
    result = extract_drift_result(report_dict)

    detected = bool(result["dataset_drift"])
    share = float(result["share_of_drifted_columns"])
    DRIFT_DETECTED.set(int(detected))
    DRIFT_SHARE.set(share)
    CHECKS.labels(result="drift" if detected else "ok").inc()

    per_feature_scores: dict[str, float] = {}
    for feature, feature_result in result.get("drift_by_columns", {}).items():
        score = feature_result.get("drift_score")
        if score is not None:
            value = float(score)
            per_feature_scores[feature] = value
            FEATURE_DRIFT_SCORE.labels(feature=feature).set(value)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("titanic-drift")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        current_path = tmp_path / "current.csv"
        html_path = tmp_path / "evidently.html"
        json_path = tmp_path / "evidently.json"
        current.to_csv(current_path, index=False)
        report.save_html(str(html_path))
        json_path.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8")

        with mlflow.start_run() as run:
            mlflow.set_tag("check_status", "success")
            mlflow.log_param("dataset_drift", detected)
            mlflow.log_param("features", ",".join(RAW_FEATURES))
            mlflow.log_param("reference_dataset_uri", f"s3://{MINIO_BUCKET}/{REFERENCE_DATASET_KEY}")
            mlflow.log_param("current_dataset_uri", current_dataset_uri)
            mlflow.log_metric("share_of_drifted_columns", share)
            mlflow.log_metric(
                "number_of_drifted_columns",
                float(result.get("number_of_drifted_columns", 0)),
            )
            for feature, score in per_feature_scores.items():
                mlflow.log_metric(f"drift_score_{feature}", score)
            mlflow.log_artifact(str(current_path), "datasets")
            mlflow.log_artifact(str(html_path), "evidently")
            mlflow.log_artifact(str(json_path), "evidently")
            run_id = run.info.run_id

    return {
        "dataset_drift": detected,
        "share_of_drifted_columns": share,
        "feature_scores": per_feature_scores,
        "current_dataset_uri": current_dataset_uri,
        "mlflow_run_id": run_id,
    }


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


@app.post("/check")
def check() -> dict:
    try:
        return run_check()
    except Exception as exc:
        CHECKS.labels(result="error").inc()
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment("titanic-drift")
            with mlflow.start_run():
                mlflow.set_tag("check_status", "error")
                mlflow.set_tag("error", str(exc)[:500])
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(exc)) from exc
