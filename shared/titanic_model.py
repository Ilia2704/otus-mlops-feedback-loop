from __future__ import annotations

from pathlib import Path
import os
import tempfile

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

RAW_FEATURES = ["Pclass", "Sex", "Age", "SibSp", "Parch", "Fare", "Embarked"]
CATEGORICAL_FEATURES = ["Pclass", "Sex", "Embarked"]
NUMERIC_FEATURES = [
    "Age",
    "SibSp",
    "Parch",
    "Fare",
    "FamilySize",
    "IsAlone",
    "IsChild",
    "FarePerPerson",
]
MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TARGET = "Survived"


def make_model() -> Pipeline:
    categorical = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    numeric = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    prep = ColumnTransformer(
        [
            ("cat", categorical, CATEGORICAL_FEATURES),
            ("num", numeric, NUMERIC_FEATURES),
        ],
        remainder="drop",
    )
    return Pipeline(
        [
            ("prep", prep),
            ("model", LogisticRegression(max_iter=1000, C=1.0, random_state=42)),
        ]
    )


def clean_features(df: pd.DataFrame) -> pd.DataFrame:
    """Select raw inputs and add a few transparent Titanic features."""
    x = df[RAW_FEATURES].copy()
    x["Pclass"] = x["Pclass"].astype(str)
    x["Sex"] = x["Sex"].fillna("unknown").astype(str)
    x["Embarked"] = x["Embarked"].fillna("unknown").astype(str)

    for column in ["Age", "SibSp", "Parch", "Fare"]:
        x[column] = pd.to_numeric(x[column], errors="coerce")

    x["FamilySize"] = x["SibSp"].fillna(0) + x["Parch"].fillna(0) + 1
    x["IsAlone"] = (x["FamilySize"] == 1).astype(int)
    x["IsChild"] = (x["Age"] < 15).fillna(False).astype(int)
    x["FarePerPerson"] = x["Fare"] / x["FamilySize"].clip(lower=1)
    return x[MODEL_FEATURES]


def train_model(df: pd.DataFrame) -> Pipeline:
    model = make_model()
    model.fit(clean_features(df), df[TARGET].astype(int))
    return model


def predict_one(model: Pipeline, payload: dict) -> int:
    frame = pd.DataFrame([payload])
    return int(model.predict(clean_features(frame))[0])


def predict_probability_one(model: Pipeline, payload: dict) -> float:
    frame = pd.DataFrame([payload])
    return float(model.predict_proba(clean_features(frame))[0, 1])


def save_model(model: Pipeline, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="model-", suffix=".joblib", dir=target.parent)
    os.close(fd)
    try:
        joblib.dump(model, tmp_name)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def load_model(path: str | Path) -> Pipeline:
    return joblib.load(path)
