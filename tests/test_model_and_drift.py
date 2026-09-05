from pathlib import Path
import sys

import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.drift import drift_dataframe
from shared.titanic_model import MODEL_FEATURES, RAW_FEATURES, clean_features, train_model


def quality(model, frame: pd.DataFrame) -> tuple[float, float]:
    x = clean_features(frame)
    y = frame["Survived"].astype(int)
    return (
        float(accuracy_score(y, model.predict(x))),
        float(roc_auc_score(y, model.predict_proba(x)[:, 1])),
    )


def test_model_uses_multiple_features():
    assert RAW_FEATURES == ["Pclass", "Sex", "Age", "SibSp", "Parch", "Fare", "Embarked"]
    for derived in ["FamilySize", "IsAlone", "IsChild", "FarePerPerson"]:
        assert derived in MODEL_FEATURES


def test_quality_drift_and_retraining_loop():
    df = pd.read_csv(ROOT / "data" / "titanic_train.csv")
    train_df, test_df = train_test_split(
        df,
        test_size=0.30,
        stratify=df["Survived"],
        random_state=42,
    )

    baseline = train_model(train_df)
    clean_accuracy, clean_auc = quality(baseline, test_df)

    drifted_test = drift_dataframe(test_df, 0.95, seed=9)
    drift_accuracy, drift_auc = quality(baseline, drifted_test)

    current_train = drift_dataframe(train_df, 0.95, seed=10)
    challenger = train_model(current_train)
    retrained_accuracy, retrained_auc = quality(challenger, drifted_test)

    assert clean_accuracy >= 0.83
    assert clean_auc >= 0.89
    assert drift_accuracy <= clean_accuracy - 0.12
    assert drift_auc <= clean_auc - 0.12
    assert retrained_accuracy >= 0.82
    assert retrained_accuracy >= drift_accuracy + 0.12
    assert retrained_auc >= 0.85
