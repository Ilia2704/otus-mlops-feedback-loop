import argparse
import random
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = pd.read_csv(ROOT / "data" / "titanic_train.csv")


def payload(row, invalid=False):
    p = row.to_dict()
    return {
        "Pclass": 4 if invalid else int(p["Pclass"]),
        "Name": str(p["Name"]),
        "Sex": str(p["Sex"]),
        "Age": None if pd.isna(p["Age"]) else float(p["Age"]),
        "SibSp": int(p["SibSp"]),
        "Parch": int(p["Parch"]),
        "Ticket": str(p["Ticket"]),
        "Fare": float(p["Fare"]),
        "Cabin": None,
        "Embarked": None if pd.isna(p["Embarked"]) else str(p["Embarked"]),
        "actual_survived": int(p["Survived"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/predict")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--invalid-rate", type=float, default=0.10)
    args = ap.parse_args()

    for i in range(args.count):
        row = DATA.sample(1).iloc[0]
        invalid = random.random() < args.invalid_rate
        r = requests.post(args.url, json=payload(row, invalid), timeout=5)
        print(i + 1, r.status_code)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
