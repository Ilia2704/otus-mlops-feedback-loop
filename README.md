# Titanic MLOps: сквозной учебный проект

Один проект для четырех занятий: мониторинг сервиса, data drift, feedback loop и alerting.

## Что внутри

```text
MinIO reference CSV -> Drifter -> FastAPI model -> Prometheus -> Grafana
       |                    |                  |             |
       |                    v                  |             +-> Alertmanager -> Telegram
       +-> current datasets -> Evidently checker -> MLflow -> MinIO artifacts
                 ^
                 |
              Airflow

Prometheus accuracy -> feedback controller -> retrainer -> MLflow Registry -> shared model -> model reload
```

Helm используется только для `kube-prometheus-stack`. Terraform нет. Остальная логика — обычные Kubernetes manifests и короткие Python-сервисы.

## Namespaces

Проект разделен на два namespace по назначению:

- `monitoring` — `kube-prometheus-stack` (Prometheus, Grafana, Alertmanager) и связанные с ним `ServiceMonitor`, `PrometheusRule`, Grafana dashboard;
- `mlops-demo` — контур обратной петли: model service, drifter, drift-checker, Airflow, controller, retrainer, MLflow и MinIO.

Таким образом, в Kubernetes Dashboard workloads не смешиваются с observability-подсистемой. У `mlops-demo` установлен label `app.kubernetes.io/part-of=feedback-loop`.

## Модель

Модель использует семь содержательных Titanic-признаков:

```text
Pclass, Sex, Age, SibSp, Parch, Fare, Embarked
```

В preprocessing добавляются четыре простых derived-признака:

```text
FamilySize, IsAlone, IsChild, FarePerPerson
```

`PassengerId`, `Name`, `Ticket`, `Cabin` не используются: это ID/high-cardinality поля, которые только усложняют учебный pipeline.

Pipeline:

```text
categorical -> imputer -> OneHotEncoder
numeric     -> imputer -> StandardScaler
                           |
                           v
                    LogisticRegression
```

На детерминированном holdout:

```text
baseline accuracy : 0.8545
baseline ROC-AUC  : 0.9061
```

Проверить:

```bash
make evaluate
```

## Что делает drift

Drifter постепенно меняет те же признаки, которые использует модель:

- `Sex` и `Embarked` получают новые категории `*_drift`;
- растет доля `Pclass=3`;
- сдвигается `Age`;
- растет `Fare`;
- немного растут `SibSp` и `Parch`.

Target `Survived` не меняется. Поэтому старая модель постепенно теряет качество, а модель, переобученная на current population, восстанавливается.

Контрольная симуляция:

```text
drift=0.00 -> accuracy 0.8545
drift=0.20 -> accuracy 0.8284
drift=0.40 -> accuracy 0.7873
drift=0.50 -> accuracy 0.7687
drift=0.60 -> accuracy 0.7313
drift=0.80 -> accuracy 0.7127
drift=0.95 -> accuracy 0.6940

after retraining at drift=0.95 -> accuracy 0.8470, ROC-AUC 0.8919
```

## Среда и быстрый запуск

Для Kubernetes-демо нужны Docker Desktop, Minikube, `kubectl` и Helm. Для локальных проверок, генерации датасета и ручного traffic-generator используется [UV](https://docs.astral.sh/uv/); `pip` и ручной virtualenv не нужны.

На macOS:

```bash
brew install uv minikube kubectl helm
uv python install 3.11
uv sync --group dev
```

Для Docker Desktop с лимитом около 9 GB используйте 4 CPU и 7 GB RAM. Перед запуском убедитесь, что Docker Desktop уже запущен:

```bash
minikube start --driver=docker --cpus=4 --memory=7168
make up
make status
make ports
```

Kubernetes Dashboard Minikube открывается отдельной командой (она занимает текущий terminal):

```bash
make kube-ui
```

`make up` собирает container images внутри Minikube. UV окружение используется только локальными командами `make check`, `make evaluate`, `make data` и traffic-generator; зависимости внутри контейнеров остаются pinned в соответствующих `requirements.txt`.

`make ports` запускает port-forward для доступных Services в фоне и сразу освобождает terminal. Проверить или остановить их можно так:

```bash
make ports-status
make ports-stop
```

Основные UI:

- Grafana: `localhost:3000`;
- Prometheus: `localhost:9090`;
- MLflow: `localhost:5000`;
- MinIO Console: `localhost:9001`, `minio` / `minio123`;
- Airflow: `localhost:8080`, `admin/admin`;
- Titanic API: `localhost:8000`.

Drifter начинает отправлять traffic автоматически. Часть запросов намеренно невалидна (`Pclass=4`), поэтому HTTP 422 — ожидаемая часть monitoring-demo.

## Главные параметры демо

`infra/k8s/common/demo-config.yaml`:

```yaml
REQUEST_INTERVAL_SECONDS: "1"       # частота запросов
DRIFT_STEP_PER_REQUEST: "0.002"     # скорость роста drift
DRIFT_MAX: "0.95"
INVALID_RATE: "0.08"
ACCURACY_THRESHOLD: "0.78"
BAD_CHECKS_BEFORE_RETRAIN: "2"
RETRAIN_COOLDOWN_SECONDS: "120"
DRIFT_CHECK_CRON: "*/2 * * * *"
```

Для очень короткого live-demo можно поставить `DRIFT_STEP_PER_REQUEST: "0.01"`.

После изменения ConfigMap:

```bash
kubectl apply -f infra/k8s/common/demo-config.yaml
kubectl -n mlops-demo rollout restart deploy/drifter deploy/feedback-controller deploy/retrainer deploy/drift-checker deploy/airflow
```

## По занятиям

- `README_01_MONITORING.md` — FastAPI + Prometheus + ServiceMonitor + Grafana.
- `README_02_DATA_DRIFT.md` — Drifter + Evidently + Airflow + MLflow.
- `README_03_FEEDBACK_LOOP.md` — контроль accuracy и автоматическое переобучение.
- `README_04_ALERTING.md` — PrometheusRule, Alertmanager, Telegram и Grafana Alerting.

## Данные

`data/titanic_train.csv` — детерминированный учебный Titanic-shaped dataset с классической схемой из 12 колонок. Он включен в архив, поэтому сеть не нужна. Подробности: `data/README.md`.

## Object storage: MinIO

`make apps` разворачивает MinIO с PVC и выполняет Job `minio-init`. Job загружает локальный `data/titanic_train.csv` в object storage и создает bucket `mlops-data` со следующими префиксами:

```text
reference/titanic_train.csv  # reference dataset
current/                     # snapshots из drift-checker и retrainer
model-artifacts/             # MLflow artifacts, включая модели
```

Drifter и Evidently checker читают reference CSV из `s3://mlops-data/reference/titanic_train.csv`; checker и retrainer сохраняют используемые current datasets в `current/`. MLflow использует `s3://mlops-data/model-artifacts/` как artifact destination.

После `make ports` откройте MinIO Console на `http://localhost:9001`. Учебные credentials: `minio` / `minio123`.

## Что взято из двух исходных проектов

Из `otus-ml-monitoring-37-test`: Titanic FastAPI service, `/metrics`, Prometheus middleware, ServiceMonitor, Helm installation `kube-prometheus-stack` и идея невалидных inference requests.

Из `otus-data-drift-search-main`: схема `drifter -> scheduled drift check -> Evidently -> MLflow` и логирование Evidently artifacts. В объединенной версии весь drift переведен на Titanic.

## Проверка

```bash
uv sync --group dev
make check
make evaluate
```

Полный аудит: `BUILD_REPORT.md` и `VALIDATION.md`.
