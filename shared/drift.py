from __future__ import annotations

import numpy as np
import pandas as pd


def drift_dataframe(df: pd.DataFrame, strength: float, seed: int | None = None) -> pd.DataFrame:
    """Create visible but recoverable covariate drift for the Titanic lecture demo.

    The target is never changed. At high strength the current population has new
    categorical values and shifted numeric distributions. A model retrained on
    the current population can learn the new representation again.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    rng = np.random.default_rng(seed)
    out = df.copy().reset_index(drop=True)
    n = len(out)

    sex_mask = rng.random(n) < strength * 0.90
    embarked_mask = rng.random(n) < strength * 0.80
    class_mask = rng.random(n) < strength * 0.55
    age_mask = (rng.random(n) < strength * 0.65) & out["Age"].notna()
    fare_mask = rng.random(n) < strength * 0.70
    sibsp_mask = rng.random(n) < strength * 0.25
    parch_mask = rng.random(n) < strength * 0.20

    out.loc[sex_mask, "Sex"] = out.loc[sex_mask, "Sex"].fillna("unknown").astype(str) + "_drift"
    out.loc[embarked_mask, "Embarked"] = (
        out.loc[embarked_mask, "Embarked"].fillna("unknown").astype(str) + "_drift"
    )
    out.loc[class_mask, "Pclass"] = 3

    age_noise = rng.normal(0, 2, n)
    out.loc[age_mask, "Age"] = np.clip(
        out.loc[age_mask, "Age"] + 18 * strength + age_noise[age_mask],
        0.5,
        100,
    )
    out.loc[fare_mask, "Fare"] = np.clip(
        out.loc[fare_mask, "Fare"] * (1 + 1.6 * strength),
        0,
        800,
    )
    out.loc[sibsp_mask, "SibSp"] = np.clip(out.loc[sibsp_mask, "SibSp"] + 1, 0, 8)
    out.loc[parch_mask, "Parch"] = np.clip(out.loc[parch_mask, "Parch"] + 1, 0, 8)
    return out


def row_payload(row: pd.Series, invalid: bool = False) -> dict:
    def optional_float(value):
        return None if pd.isna(value) else float(value)

    def optional_str(value):
        return None if pd.isna(value) else str(value)

    pclass = 4 if invalid else int(row["Pclass"])
    return {
        "Pclass": pclass,
        "Name": str(row.get("Name", "Passenger")),
        "Sex": str(row["Sex"]),
        "Age": optional_float(row.get("Age")),
        "SibSp": int(row.get("SibSp", 0)),
        "Parch": int(row.get("Parch", 0)),
        "Ticket": str(row.get("Ticket", "DEMO")),
        "Fare": float(row.get("Fare", 0.0)),
        "Cabin": optional_str(row.get("Cabin")),
        "Embarked": optional_str(row.get("Embarked")),
        "actual_survived": int(row["Survived"]),
    }
