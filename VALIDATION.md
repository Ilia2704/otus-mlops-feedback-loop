# VALIDATION — финальная проверка проекта

## 1. Model/data validation

Dataset regenerated from `data/generate_dataset.py`:

```text
rows          = 891
columns       = 12
survival rate = 0.409
```

Model inputs:

```text
raw     = 7
engineered = 4
```

`make evaluate`:

```text
baseline accuracy : 0.8545
baseline ROC-AUC  : 0.9061
drifted accuracy  : 0.6940
drifted ROC-AUC   : 0.7069
retrained accuracy: 0.8470
retrained ROC-AUC : 0.8919
```

Baseline degradation by drift strength:

```text
0.00 -> accuracy 0.8545, ROC-AUC 0.9061
0.20 -> accuracy 0.8284, ROC-AUC 0.8868
0.40 -> accuracy 0.7873, ROC-AUC 0.8513
0.50 -> accuracy 0.7687, ROC-AUC 0.8226
0.60 -> accuracy 0.7313, ROC-AUC 0.7877
0.80 -> accuracy 0.7127, ROC-AUC 0.7618
0.95 -> accuracy 0.6940, ROC-AUC 0.7069
```

Это дает достаточный запас между baseline `0.85` и retraining threshold `0.78`.

## 2. Python tests

Проверяются:

- семь raw model features;
- четыре engineered features;
- baseline accuracy >= 0.83;
- baseline ROC-AUC >= 0.89;
- сильный drift заметно ухудшает accuracy/AUC;
- retraining восстанавливает accuracy >= 0.82 и ROC-AUC >= 0.85.

Команды:

```bash
python tests/static_check.py
python tests/integration_static_check.py
pytest -q
python -m compileall -q .
```

## 3. Kubernetes/Helm wiring

Статически проверяется:

- Terraform отсутствует;
- все YAML parse;
- Grafana dashboard JSON parse;
- custom images из manifests присутствуют в build script;
- internal URLs из ConfigMap разрешаются в существующие Services;
- instrumented Services имеют `monitoring: prometheus` и port `http`;
- ServiceMonitor выбирает эти Services;
- PrometheusRule содержит demo alerts;
- model service и retrainer используют общий model PVC;
- retrainer регистрирует версию в MLflow Registry, использует `Staging`/`Production` и имеет rollback API;
- MLflow/Airflow/Drifter/Checker/Controller wiring согласован;
- Helm устанавливает pinned `kube-prometheus-stack 89.2.2` с `--wait`.

## 4. Monitoring consistency

Dashboard использует реальные метрики проекта:

```text
starlette_requests_total
titanic_correct_predictions_total
titanic_labeled_predictions_total
titanic_drift_detected
titanic_feature_drift_score
titanic_retraining_roc_auc
titanic_input_age_years_bucket
```

Alert threshold и controller threshold синхронизированы на `0.78`.

## 5. Data drift consistency

Evidently и model pipeline используют одинаковые raw model inputs:

```text
Pclass, Sex, Age, SibSp, Parch, Fare, Embarked
```

Derived features считаются только внутри model preprocessing и поэтому не дублируются в raw drift monitoring.

## 6. Alerting

Проверено статически:

- `TitanicServiceDown` использует `up == 0 or absent(...)`;
- Telegram routing ограничен `alertname=~"Titanic.*"`;
- secrets в репозиторий не включены;
- Grafana Alerting описан отдельно в README.

## 7. Packaging checks

Перед ZIP удаляются:

```text
__pycache__
.pytest_cache
*.pyc
.DS_Store
```

После создания ZIP выполняются:

```text
unzip -t
clean extraction
static_check.py
integration_static_check.py
pytest -q
bash -n scripts/*.sh
```

## 8. Ограничение sandbox

В текущем окружении нет Docker daemon, Minikube, kubectl и Helm, поэтому невозможно честно выполнить full runtime smoke test Kubernetes-кластера.

Не проверены фактическим запуском:

- `helm upgrade --install`;
- Docker builds;
- pod startup;
- live Prometheus scrape;
- Grafana UI;
- реальная Telegram delivery.

Всё, что можно проверить без реального кластера, проверяется автоматически через `make check` и `make evaluate`.
