from __future__ import annotations

import io
import math
import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import mlflow
import mlflow.sklearn
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from prometheus_client import Counter, Gauge
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from starlette_exporter import PrometheusMiddleware, handle_metrics

from shared.object_store import put_text
from shared.titanic_model import MODEL_FEATURES, clean_features, save_model, train_model

MODEL_PATH = Path(os.getenv("MODEL_PATH", "/models/model.joblib"))
DRIFTER_URL = os.getenv("DRIFTER_URL", "http://drifter:8001")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
RETRAIN_ROWS = int(os.getenv("RETRAIN_ROWS", "800"))
MODEL_REGISTRY_NAME = os.getenv("MODEL_REGISTRY_NAME", "titanic-survival-model")
AUTO_PROMOTE_MODEL = os.getenv("AUTO_PROMOTE_MODEL", "true").lower() == "true"
PROMOTION_MIN_ACCURACY = float(os.getenv("PROMOTION_MIN_ACCURACY", "0.80"))
PROMOTION_MIN_ROC_AUC = float(os.getenv("PROMOTION_MIN_ROC_AUC", "0.85"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "mlops-data")
CURRENT_DATASET_PREFIX = os.getenv("CURRENT_DATASET_PREFIX", "current")

app = FastAPI(title="Titanic retrainer")
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", handle_metrics)

RUNS = Counter("titanic_retraining_runs", "Retraining runs", ["result"])
LAST_ACCURACY = Gauge("titanic_retraining_accuracy", "Validation accuracy of the last retrain")
LAST_ROC_AUC = Gauge("titanic_retraining_roc_auc", "Validation ROC-AUC of the last retrain")
ACTIVE_MODEL_VERSION = Gauge("titanic_active_model_version", "MLflow Production model version")
REGISTRY_EVENTS = Counter("titanic_model_registry_events", "MLflow Registry lifecycle events", ["event"])


def registry_client() -> MlflowClient:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    return MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)


def ensure_registered_model(client: MlflowClient) -> None:
    """Create the Registry entry once; concurrent first retrains are harmless."""
    try:
        client.get_registered_model(MODEL_REGISTRY_NAME)
    except MlflowException:
        try:
            client.create_registered_model(
                MODEL_REGISTRY_NAME,
                tags={"project": "titanic-mlops", "owner": "feedback-loop"},
                description="Titanic survival model managed by the feedback loop.",
            )
        except MlflowException:
            # Another retrainer may have created it between get and create.
            client.get_registered_model(MODEL_REGISTRY_NAME)


def quality_gate(accuracy: float, roc_auc: float) -> tuple[bool, str]:
    if not math.isfinite(accuracy) or not math.isfinite(roc_auc):
        return False, "validation metrics are missing or non-finite"
    if accuracy < PROMOTION_MIN_ACCURACY:
        return False, f"accuracy {accuracy:.4f} < {PROMOTION_MIN_ACCURACY:.4f}"
    if roc_auc < PROMOTION_MIN_ROC_AUC:
        return False, f"roc_auc {roc_auc:.4f} < {PROMOTION_MIN_ROC_AUC:.4f}"
    return True, "quality gate passed"


def production_version(client: MlflowClient) -> str | None:
    versions = client.get_latest_versions(MODEL_REGISTRY_NAME, stages=["Production"])
    return versions[0].version if versions else None


def promote_version(client: MlflowClient, version: str, reason: str) -> dict:
    """Promote a registered candidate and make that exact Registry artifact serve traffic."""
    candidate = client.get_model_version(MODEL_REGISTRY_NAME, version)
    if not candidate.run_id:
        raise ValueError(f"model version {version} is not linked to an MLflow run")

    metrics = client.get_run(candidate.run_id).data.metrics
    accuracy = float(metrics.get("validation_accuracy", float("nan")))
    roc_auc = float(metrics.get("validation_roc_auc", float("nan")))
    accepted, detail = quality_gate(accuracy, roc_auc)
    if not accepted:
        client.set_model_version_tag(MODEL_REGISTRY_NAME, version, "approval_status", "rejected")
        client.set_model_version_tag(MODEL_REGISTRY_NAME, version, "rejection_reason", detail)
        REGISTRY_EVENTS.labels(event="rejected").inc()
        raise ValueError(f"candidate {version} rejected: {detail}")

    # Load from the Registry, rather than from the in-memory training result, so
    # the version declared Production is exactly the artifact deployed on the PVC.
    model = mlflow.sklearn.load_model(f"models:/{MODEL_REGISTRY_NAME}/{version}")
    previous = production_version(client)
    client.transition_model_version_stage(
        MODEL_REGISTRY_NAME,
        version,
        stage="Production",
        archive_existing_versions=True,
    )
    save_model(model, MODEL_PATH)
    client.set_model_version_tag(MODEL_REGISTRY_NAME, version, "approval_status", "approved")
    client.set_model_version_tag(MODEL_REGISTRY_NAME, version, "promotion_reason", reason)
    if previous and previous != version:
        client.set_model_version_tag(MODEL_REGISTRY_NAME, previous, "replaced_by", version)
    ACTIVE_MODEL_VERSION.set(float(version))
    REGISTRY_EVENTS.labels(event="promoted").inc()
    return {
        "model_name": MODEL_REGISTRY_NAME,
        "model_version": version,
        "previous_production_version": previous,
        "promotion_status": "Production",
        "quality_gate": detail,
    }


def register_candidate(
    client: MlflowClient,
    run_id: str,
    accuracy: float,
    roc_auc: float,
) -> str:
    ensure_registered_model(client)
    version = client.create_model_version(
        MODEL_REGISTRY_NAME,
        source=f"runs:/{run_id}/model",
        run_id=run_id,
        description="Candidate trained by the automatic Titanic feedback loop.",
    ).version
    client.transition_model_version_stage(MODEL_REGISTRY_NAME, version, stage="Staging")
    accepted, detail = quality_gate(accuracy, roc_auc)
    client.set_model_version_tag(
        MODEL_REGISTRY_NAME,
        version,
        "approval_status",
        "pending_auto_promotion" if accepted else "rejected",
    )
    client.set_model_version_tag(MODEL_REGISTRY_NAME, version, "quality_gate", detail)
    REGISTRY_EVENTS.labels(event="registered").inc()
    return version


def retrain_once() -> dict:
    response = requests.get(f"{DRIFTER_URL}/data", params={"rows": RETRAIN_ROWS}, timeout=30)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    training_dataset_key = (
        f"{CURRENT_DATASET_PREFIX}/retraining-"
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex}.csv"
    )
    training_dataset_uri = put_text(
        MINIO_BUCKET,
        training_dataset_key,
        df.to_csv(index=False),
        content_type="text/csv",
    )
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

    LAST_ACCURACY.set(accuracy)
    LAST_ROC_AUC.set(roc_auc)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("titanic-retraining")
    with mlflow.start_run() as run:
        mlflow.log_param("rows", len(df))
        mlflow.log_param("model", "LogisticRegression")
        mlflow.log_param("features", ",".join(MODEL_FEATURES))
        mlflow.log_param("training_dataset_uri", training_dataset_uri)
        mlflow.log_metric("validation_accuracy", accuracy)
        mlflow.log_metric("validation_roc_auc", roc_auc)
        mlflow.log_metric("survival_rate", float(df["Survived"].mean()))
        mlflow.sklearn.log_model(model, artifact_path="model")
        run_id = run.info.run_id

    client = registry_client()
    version = register_candidate(client, run_id, accuracy, roc_auc)
    if AUTO_PROMOTE_MODEL:
        lifecycle = promote_version(client, version, reason="automatic quality-gated promotion")
    else:
        lifecycle = {
            "model_name": MODEL_REGISTRY_NAME,
            "model_version": version,
            "promotion_status": "Staging",
            "approval_required": True,
        }

    RUNS.labels(result="success").inc()
    return {
        "status": "retrained",
        "validation_accuracy": accuracy,
        "validation_roc_auc": roc_auc,
        "mlflow_run_id": run_id,
        **lifecycle,
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


@app.post("/approve/{version}")
def approve(version: str) -> dict:
    """Manually promote a staged candidate which still passes the quality gate."""
    try:
        return promote_version(registry_client(), version, reason="manual approval")
    except Exception as exc:
        REGISTRY_EVENTS.labels(event="approval_error").inc()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/rollback/{version}")
def rollback(version: str) -> dict:
    """Restore an archived/staged Registry version and deploy that exact artifact."""
    try:
        client = registry_client()
        target = client.get_model_version(MODEL_REGISTRY_NAME, version)
        model = mlflow.sklearn.load_model(f"models:/{MODEL_REGISTRY_NAME}/{version}")
        previous = production_version(client)
        client.transition_model_version_stage(
            MODEL_REGISTRY_NAME,
            version,
            stage="Production",
            archive_existing_versions=True,
        )
        save_model(model, MODEL_PATH)
        client.set_model_version_tag(MODEL_REGISTRY_NAME, version, "rollback_status", "restored")
        if previous and previous != version:
            client.set_model_version_tag(MODEL_REGISTRY_NAME, previous, "rolled_back_to", version)
        ACTIVE_MODEL_VERSION.set(float(version))
        REGISTRY_EVENTS.labels(event="rolled_back").inc()
        return {
            "status": "rolled_back",
            "model_name": MODEL_REGISTRY_NAME,
            "model_version": target.version,
            "previous_production_version": previous,
        }
    except Exception as exc:
        REGISTRY_EVENTS.labels(event="rollback_error").inc()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
