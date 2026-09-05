# BUILD REPORT — Titanic MLOps end-to-end demo

## 1. Итог

Два исходных учебных проекта объединены в один сквозной стенд без Terraform.

Стек:

```text
Kubernetes + Helm
FastAPI
Prometheus + Prometheus Operator + ServiceMonitor
Grafana
Alertmanager + Telegram
Evidently
MLflow
Airflow
scikit-learn
```

Helm нужен только для установки `kube-prometheus-stack`. Все demo-приложения описаны обычными Kubernetes manifests.

## 2. Архитектура

```text
                      +--------------------+
                      |      Grafana       |
                      +---------^----------+
                                |
+---------+    HTTP    +--------+---------+       +-------------+
| Drifter |----------->| Titanic FastAPI  |------>| Prometheus  |
+----+----+             +--------+---------+       +------+------+ 
     |                           ^                        |
     | current CSV               | model PVC              |
     v                           |                        v
+----+-------------+             |                +------+-----------+
| Evidently checker|----> MLflow |                | feedback controller|
+----^-------------+             |                +------+-----------+
     |                           |                        |
  Airflow                         +------ retrainer <------+

PrometheusRule -> Alertmanager -> Telegram
Grafana Alert Rule -------------> Telegram Contact Point
```

## 3. Dataset

В архиве лежит автономный `data/titanic_train.csv`:

- 891 строка;
- 12 колонок;
- target `Survived`;
- missing values в `Age` и `Embarked`;
- schema совместима с классическим Titanic train.csv.

Dataset детерминированно генерируется `data/generate_dataset.py`.

## 4. Model pipeline

### Raw features

```text
Pclass
Sex
Age
SibSp
Parch
Fare
Embarked
```

### Derived features

```text
FamilySize
IsAlone
IsChild
FarePerPerson
```

### Исключены

```text
PassengerId  -> ID
Name         -> high cardinality
Ticket       -> high cardinality
Cabin        -> high cardinality + missing
Survived     -> target
```

### Pipeline

```text
categorical -> SimpleImputer -> OneHotEncoder(handle_unknown="ignore")
numeric     -> SimpleImputer -> StandardScaler
                                    |
                                    v
                            LogisticRegression
```

Модель специально оставлена простой и объяснимой для курса, но качество уже не игрушечное.

Holdout:

```text
accuracy = 0.8545
ROC-AUC  = 0.9061
```

## 5. Demo 01 — Monitoring

### Основные файлы

- `apps/model_service/main.py`
- `shared/titanic_model.py`
- `demos/01_monitoring/send_requests.py`
- `infra/k8s/01_monitoring/model-service.yaml`
- `infra/k8s/01_monitoring/servicemonitor.yaml`
- `infra/k8s/01_monitoring/grafana-dashboard.yaml`
- `infra/helm/monitoring-values.yaml`
- `README_01_MONITORING.md`

### Метрики

HTTP metrics идут через `starlette_exporter`.

Custom metrics:

```text
titanic_predictions_total
titanic_labeled_predictions_total
titanic_correct_predictions_total
titanic_unknown_category_total
titanic_model_reloads_total
titanic_input_category_total
titanic_input_age_years
titanic_input_fare
titanic_input_family_size
titanic_survival_probability
```

Часть traffic намеренно невалидна: `Pclass=4` отклоняется Pydantic и дает HTTP 422.

Grafana dashboard содержит HTTP, accuracy, prediction distribution, drift, retraining и input distributions.

## 6. Demo 02 — Data Drift

### Основные файлы

- `shared/drift.py`
- `demos/02_data_drift/drifter/main.py`
- `demos/02_data_drift/drift_checker/main.py`
- `demos/02_data_drift/airflow/drift_detection.py`
- `infra/k8s/02_data_drift/*`
- `infra/k8s/common/mlflow.yaml`
- `README_02_DATA_DRIFT.md`

### Drift profile

При росте `strength` меняются все семь raw model inputs:

- `Sex` -> новые `*_drift` categories;
- `Embarked` -> новые `*_drift` categories;
- `Pclass` -> больше 3 класса;
- `Age` -> сдвиг вверх;
- `Fare` -> сдвиг вверх;
- `SibSp`, `Parch` -> небольшой сдвиг вверх.

`Survived` не меняется.

Drifter одновременно:

1. посылает current objects в inference service;
2. отдает current dataset через `/data`.

Evidently проверяет ровно те семь raw features, на которых основана модель.

Prometheus metrics:

```text
titanic_drift_detected
titanic_drift_share
titanic_feature_drift_score{feature="..."}
```

Каждый check пишет MLflow run с metrics и artifacts:

```text
current.csv
evidently.html
evidently.json
```

## 7. Demo 03 — Feedback loop

### Основные файлы

- `demos/03_feedback_loop/controller/main.py`
- `demos/03_feedback_loop/retrainer/main.py`
- `infra/k8s/03_feedback_loop/*`
- `infra/k8s/common/model-pvc.yaml`
- `README_03_FEEDBACK_LOOP.md`

### Логика

Учебный traffic передает `actual_survived`, поэтому online accuracy доступна без target delay.

Controller делает Prometheus query:

```promql
sum(rate(titanic_correct_predictions_total[2m]))
/
clamp_min(sum(rate(titanic_labeled_predictions_total[2m])), 0.001)
```

При двух последовательных проверках ниже `0.78` вызывается retrainer.

Retrainer:

1. получает current dataset;
2. делает stratified split;
3. обучает тот же pipeline;
4. считает accuracy + ROC-AUC;
5. пишет run в `titanic-retraining`;
6. сохраняет model artifact;
7. атомарно обновляет shared PVC.

Model service reload-ит artifact по изменению `mtime`.

Контрольная симуляция:

```text
baseline clean accuracy : 0.8545
baseline clean ROC-AUC  : 0.9061
baseline drift=0.95 acc : 0.6940
baseline drift=0.95 AUC : 0.7069
retrained accuracy      : 0.8470
retrained ROC-AUC       : 0.8919
```

Динамика baseline:

```text
drift=0.00 -> 0.8545
drift=0.20 -> 0.8284
drift=0.40 -> 0.7873
drift=0.50 -> 0.7687
drift=0.60 -> 0.7313
drift=0.80 -> 0.7127
drift=0.95 -> 0.6940
```

## 8. Demo 04 — Alerting

### Файлы

- `infra/k8s/04_alerting/prometheus-rules.yaml`
- `infra/helm/telegram-values.example.yaml`
- `README_04_ALERTING.md`

Prometheus alerts:

```text
TitanicServiceDown
TitanicHighHttpErrorRate
TitanicAccuracyLow (< 0.78)
TitanicDataDrift
```

`TitanicServiceDown` покрывает и `up == 0`, и полное исчезновение target через `absent()`.

Alertmanager маршрутизирует в Telegram только `Titanic*` alerts. Системные alerts monitoring stack идут в `null` receiver.

Grafana Alerting оставлен отдельным UI-demo.

## 9. Настройки лекции

`infra/k8s/common/demo-config.yaml`:

```yaml
REQUEST_INTERVAL_SECONDS: "1"
DRIFT_STEP_PER_REQUEST: "0.002"
DRIFT_MAX: "0.95"
INVALID_RATE: "0.08"
DRIFT_ROWS: "400"
DRIFT_CHECK_CRON: "*/2 * * * *"
CHECK_INTERVAL_SECONDS: "15"
ACCURACY_THRESHOLD: "0.78"
ACCURACY_WINDOW: "2m"
BAD_CHECKS_BEFORE_RETRAIN: "2"
RETRAIN_COOLDOWN_SECONDS: "120"
RETRAIN_ROWS: "800"
```

Две главные ручки live-demo:

```text
REQUEST_INTERVAL_SECONDS
DRIFT_STEP_PER_REQUEST
```

## 10. Структура проекта

```text
apps/model_service/                 inference
shared/                             общая model/drift logic
data/                               dataset + generator
demos/01_monitoring/                traffic generator
demos/02_data_drift/                drifter, Evidently, Airflow DAG
demos/03_feedback_loop/             controller, retrainer
infra/helm/                          только monitoring stack
infra/k8s/common/                    shared K8s objects
infra/k8s/01_monitoring/             service, ServiceMonitor, dashboard
infra/k8s/02_data_drift/             Airflow, Drifter, checker
infra/k8s/03_feedback_loop/          controller, retrainer
infra/k8s/04_alerting/               PrometheusRule
docs/slides/                         lecture slides
scripts/                             install/build/deploy/reset/evaluate
tests/                               static + model/drift tests
```

## 11. Что намеренно не добавлено

- Terraform;
- MinIO;
- отдельный PostgreSQL для MLflow;
- сложный feature store;
- сложная model registry promotion logic.

Для лекции это лишняя инфраструктура. Основной MLOps flow остается виден полностью.

## 12. Быстрые команды

```bash
make data       # воспроизвести dataset
make evaluate   # проверить качество + drift/retrain effect
make check      # static checks + pytest
make up         # monitoring + images + apps
make reset      # вернуть drift/model к baseline
```
