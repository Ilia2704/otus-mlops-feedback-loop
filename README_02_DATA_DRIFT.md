# 02. Поиск отклонений и data drift

## Цель

Реализовать на Titanic схему из drift-репозитория: Drifter формирует current population, Airflow регулярно запускает Evidently check, каждый check сохраняется в MLflow и одновременно отдает метрики в Prometheus.

## Архитектура

```text
MinIO reference CSV -------------------------+
                                             |
Drifter -> current Titanic CSV -> Evidently checker -> MLflow
                                      |
                                      +-> Prometheus
                                      ^
                                      |
                                   Airflow DAG
```

## Слайд из лекции

![Drift architecture](docs/slides/02_drift_architecture.png)

## Что именно дрифтует

Evidently проверяет все семь raw features модели:

```text
Pclass, Sex, Age, SibSp, Parch, Fare, Embarked
```

Drifter постепенно делает:

```text
Sex       -> часть значений получает *_drift
Embarked  -> часть значений получает *_drift
Pclass    -> растет доля 3 класса
Age       -> распределение сдвигается вверх
Fare      -> распределение сдвигается вверх
SibSp     -> небольшое увеличение
Parch     -> небольшое увеличение
```

Это специально контролируемый lecture drift. Target `Survived` остается исходным.

## Что делает Evidently checker

`POST /check`:

1. читает reference `s3://mlops-data/reference/titanic_train.csv` из MinIO;
2. забирает current dataset у Drifter;
3. запускает `DataDriftPreset`;
4. экспортирует `titanic_drift_detected`, `titanic_drift_share` и `titanic_feature_drift_score{feature=...}`;
5. создает MLflow run;
6. логирует per-feature drift score;
7. сохраняет используемый current CSV в `s3://mlops-data/current/`;
8. сохраняет `current.csv`, `evidently.html`, `evidently.json` в MLflow, чьи artifacts находятся в MinIO `model-artifacts/`.

Airflow вызывает checker по `DRIFT_CHECK_CRON`.

## Запуск

```bash
make infra
make images
make apps
make ports
```

Ручной check:

```bash
curl -X POST http://127.0.0.1:8002/check
```

Сохранить текущую drifted выборку локально:

```bash
curl --fail --silent --show-error \
  "http://127.0.0.1:8001/data?rows=400" > current-drift.csv
```

Без port-forward можно получить тот же CSV прямо из Pod; команда завершается сразу и сохраняет файл в текущую директорию:

```bash
kubectl -n mlops-demo exec deployment/drifter -- python -c \
  'import requests; response = requests.get("http://127.0.0.1:8001/data?rows=400", timeout=10); response.raise_for_status(); print(response.text, end="")' \
  > current-drift.csv
```

В MLflow откройте experiment `titanic-drift`. Каждый вызов `/check` — отдельный run.
