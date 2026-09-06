from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]

assert not (ROOT / "infra/terraform").exists()

# Build script must build every custom image referenced in Kubernetes.
build = (ROOT / "scripts/build_images.sh").read_text()
custom_images = set()
services = {}
monitoring_services = set()
for path in (ROOT / "infra/k8s").rglob("*.yaml"):
    for doc in yaml.safe_load_all(path.read_text()):
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind")
        if kind == "Deployment":
            for c in doc["spec"]["template"]["spec"].get("containers", []):
                image = c.get("image", "")
                if image.endswith(":demo"):
                    custom_images.add(image)
        if kind == "Service":
            name = doc["metadata"]["name"]
            services[name] = doc
            if doc["metadata"].get("labels", {}).get("monitoring") == "prometheus":
                monitoring_services.add(name)
                assert any(p.get("name") == "http" for p in doc["spec"]["ports"]), name

for image in custom_images:
    assert f"-t {image}" in build, image

# Internal URLs in demo-config must resolve to Service names.
config = yaml.safe_load((ROOT / "infra/k8s/common/demo-config.yaml").read_text())["data"]
for key in [
    "MODEL_URL",
    "DRIFTER_URL",
    "DRIFT_CHECKER_URL",
    "RETRAINER_URL",
    "MLFLOW_TRACKING_URI",
    "MINIO_ENDPOINT",
]:
    host = re.sub(r"^https?://", "", config[key]).split(":", 1)[0].split(".", 1)[0]
    assert host in services, (key, host, sorted(services))
assert config["ACCURACY_THRESHOLD"] == "0.78"
assert config["MODEL_REGISTRY_NAME"] == "titanic-survival-model"
assert config["AUTO_PROMOTE_MODEL"] in {"true", "false"}
assert config["MINIO_BUCKET"] == "mlops-data"

# ServiceMonitor intentionally selects all instrumented demo services.
sm = yaml.safe_load((ROOT / "infra/k8s/01_monitoring/servicemonitor.yaml").read_text())
assert sm["metadata"]["namespace"] == "monitoring"
assert sm["spec"]["selector"]["matchLabels"] == {"monitoring": "prometheus"}
assert sm["spec"]["endpoints"][0]["port"] == "http"
assert {"titanic-model", "drifter", "drift-checker", "retrainer", "feedback-controller"} <= monitoring_services

# Dashboard and rules must reference the core demo signals.
dashboard = (ROOT / "infra/k8s/01_monitoring/grafana-dashboard.yaml").read_text()
rules = (ROOT / "infra/k8s/04_alerting/prometheus-rules.yaml").read_text()
assert yaml.safe_load(dashboard)["metadata"]["namespace"] == "monitoring"
assert yaml.safe_load(rules)["metadata"]["namespace"] == "monitoring"
for metric in [
    "starlette_requests_total",
    "titanic_correct_predictions_total",
    "titanic_labeled_predictions_total",
    "titanic_drift_detected",
    "titanic_feature_drift_score",
    "titanic_retraining_roc_auc",
    "titanic_input_age_years_bucket",
]:
    assert metric in dashboard or metric in rules, metric
assert "< 0.78" in rules

# Monitoring stack must be installed through Helm, matching the source monitoring project.
install = (ROOT / "scripts/install_monitoring.sh").read_text()
for token in [
    "prometheus-community/kube-prometheus-stack",
    "helm upgrade --install monitoring",
    "monitoring-values.yaml",
    "--version",
    "89.2.2",
    "--wait",
]:
    assert token in install, token

values = yaml.safe_load((ROOT / "infra/helm/monitoring-values.yaml").read_text())
assert values["prometheus"]["prometheusSpec"]["serviceMonitorSelectorNilUsesHelmValues"] is False
assert values["prometheus"]["prometheusSpec"]["ruleSelectorNilUsesHelmValues"] is False
assert values["grafana"]["sidecar"]["dashboards"]["searchNamespace"] == "ALL"

telegram = (ROOT / "infra/helm/telegram-values.example.yaml").read_text()
for token in ["telegram_configs", "bot_token", "chat_id", "send_resolved", "alertname=~\"Titanic.*\"", 'receiver: "null"']:
    assert token in telegram, token

rules_text = (ROOT / "infra/k8s/04_alerting/prometheus-rules.yaml").read_text()
assert 'absent(up{job="titanic-model"})' in rules_text

# Keep deployment order stable and wait until demo pods are running.
deploy_script = (ROOT / "scripts/deploy_apps.sh").read_text()
assert "rollout status" in deploy_script

# Model, Evidently and docs must all use the same seven raw inputs.
model_code = (ROOT / "shared/titanic_model.py").read_text()
drift_checker = (ROOT / "demos/02_data_drift/drift_checker/main.py").read_text()
for feature in ["Pclass", "Sex", "Age", "SibSp", "Parch", "Fare", "Embarked"]:
    assert feature in model_code
    assert feature in drift_checker

# Retraining must make MLflow Registry the source of the deployed model, not
# merely an artifact store. Staging, Production promotion and rollback are
# intentionally checked as source-level contracts because no cluster is needed.
retrainer = (ROOT / "demos/03_feedback_loop/retrainer/main.py").read_text()
for token in [
    "create_registered_model",
    "create_model_version",
    'stage="Staging"',
    'stage="Production"',
    "mlflow.sklearn.log_model",
    "mlflow.sklearn.load_model",
    '"/approve/{version}"',
    '"/rollback/{version}"',
    "titanic_active_model_version",
]:
    assert token in retrainer, token

minio = (ROOT / "infra/k8s/common/minio.yaml").read_text()
minio_init = (ROOT / "infra/k8s/common/minio-init.yaml").read_text()
mlflow_manifest = (ROOT / "infra/k8s/common/mlflow.yaml").read_text()
for token in ["minio-credentials", "minio-pvc", "containerPort: 9000", "containerPort: 9001"]:
    assert token in minio, token
for token in ["reference/titanic_train.csv", "for prefix in current model-artifacts", "mc pipe"]:
    assert token in minio_init, token
assert "s3://mlops-data/model-artifacts" in mlflow_manifest
assert "titanic-mlflow:demo" in mlflow_manifest

print("integration static checks: OK")
