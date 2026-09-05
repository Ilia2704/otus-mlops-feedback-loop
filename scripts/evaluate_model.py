from pathlib import Path
import sys

import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.drift import drift_dataframe
from shared.titanic_model import clean_features, train_model


def metrics(model, frame: pd.DataFrame) -> tuple[float, float]:
    x = clean_features(frame)
    y = frame["Survived"].astype(int)
    prediction = model.predict(x)
    probability = model.predict_proba(x)[:, 1]
    return float(accuracy_score(y, prediction)), float(roc_auc_score(y, probability))


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "titanic_train.csv")
    train_df, test_df = train_test_split(
        df,
        test_size=0.30,
        stratify=df["Survived"],
        random_state=42,
    )

    baseline = train_model(train_df)
    clean_accuracy, clean_auc = metrics(baseline, test_df)

    drifted_test = drift_dataframe(test_df, 0.95, seed=9)
    drift_accuracy, drift_auc = metrics(baseline, drifted_test)

    drifted_train = drift_dataframe(train_df, 0.95, seed=10)
    challenger = train_model(drifted_train)
    retrained_accuracy, retrained_auc = metrics(challenger, drifted_test)

    print(f"baseline accuracy : {clean_accuracy:.4f}")
    print(f"baseline ROC-AUC  : {clean_auc:.4f}")
    print(f"drifted accuracy  : {drift_accuracy:.4f}")
    print(f"drifted ROC-AUC   : {drift_auc:.4f}")
    print(f"retrained accuracy: {retrained_accuracy:.4f}")
    print(f"retrained ROC-AUC : {retrained_auc:.4f}")


if __name__ == "__main__":
    main()
