import json
import os
import urllib.request
from airflow import DAG
from airflow.operators.python import PythonOperator
from pendulum import datetime


def check_drift():
    url = os.getenv("DRIFT_CHECKER_URL", "http://drift-checker:8002")
    request = urllib.request.Request(f"{url}/check", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        print(json.loads(response.read().decode("utf-8")))


with DAG(
    dag_id="titanic_drift_detection",
    start_date=datetime(2024, 1, 1, tz="UTC"),
    schedule=os.getenv("DRIFT_CHECK_CRON", "*/2 * * * *"),
    catchup=False,
    tags=["titanic", "drift"],
) as dag:
    PythonOperator(task_id="evidently_check", python_callable=check_drift)
