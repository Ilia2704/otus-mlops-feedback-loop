from pathlib import Path

import numpy as np
import pandas as pd

# Deterministic Titanic-shaped lecture data. The schema is compatible with the
# classic Kaggle train.csv, but the rows are generated locally so the demo works offline.
rng = np.random.default_rng(42)
n = 891

pclass = rng.choice([1, 2, 3], n, p=[0.24, 0.21, 0.55])
sex = rng.choice(["male", "female"], n, p=[0.65, 0.35])
age = np.clip(rng.normal(30, 14, n), 0.5, 80)
sibsp = np.clip(rng.poisson(0.5, n), 0, 5)
parch = np.clip(rng.poisson(0.4, n), 0, 5)
family_size = sibsp + parch + 1
embarked = rng.choice(["S", "C", "Q"], n, p=[0.72, 0.19, 0.09])

fare_base = np.select([pclass == 1, pclass == 2], [70.0, 25.0], default=12.0)
fare = np.clip(fare_base * rng.lognormal(0, 0.45, n), 3.0, 500.0)

# Several meaningful features influence survival. This makes the baseline model
# genuinely multi-feature and gives a stable holdout accuracy around 0.85.
logit = (
    -3.30
    + 4.50 * (sex == "female")
    + 1.70 * (pclass == 1)
    + 0.90 * (pclass == 2)
    + 1.00 * (age < 15)
    + 0.50 * ((family_size >= 2) & (family_size <= 4))
    - 1.20 * (family_size >= 5)
    + 0.40 * (embarked == "C")
    - 0.025 * np.maximum(age - 30, 0)
    + 0.003 * np.minimum(fare, 100)
)
probability = 1 / (1 + np.exp(-logit))
survived = rng.binomial(1, probability)

age[rng.random(n) < 0.18] = np.nan
embarked_obj = embarked.astype(object)
embarked_obj[rng.random(n) < 0.02] = None

# Name/Ticket/Cabin stay in the API-compatible schema but are intentionally not
# model inputs in this demo: they are identifiers/high-cardinality fields.
df = pd.DataFrame(
    {
        "PassengerId": np.arange(1, n + 1),
        "Survived": survived,
        "Pclass": pclass,
        "Name": [f"Passenger {i}" for i in range(1, n + 1)],
        "Sex": sex,
        "Age": age,
        "SibSp": sibsp,
        "Parch": parch,
        "Ticket": [f"TKT{i:05d}" for i in range(1, n + 1)],
        "Fare": fare.round(4),
        "Cabin": [None] * n,
        "Embarked": embarked_obj,
    }
)

out = Path(__file__).with_name("titanic_train.csv")
df.to_csv(out, index=False)
print(out)
print(f"rows={len(df)} survival_rate={df['Survived'].mean():.3f}")
