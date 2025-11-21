# src/train_model.py

from pathlib import Path
import pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, log_loss
import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "ufc_features.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_model.joblib"


def main():
    print(f"Loading cleaned data from: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded shape: {df.shape}")

    target_col = "win_red"
    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found in dataset")

    # Split into X (features) and y (label)
    X = df.drop(columns=[target_col])
    y = df[target_col]

    print(f"Features shape: {X.shape}")
    print(f"Target shape:   {y.shape}")

    # Train/test split (20/80)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    print("Training XGBoost model...")
    model = XGBClassifier(
        n_estimators=400,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=42,
        n_jobs=4,
    )

    model.fit(X_tr, y_tr)

    # Evaluate
    p_te = model.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, p_te)
    ll = log_loss(y_te, p_te)

    print("✅ Training complete")
    print(f"   ROC-AUC: {auc:.3f}")
    print(f"   LogLoss: {ll:.3f}")

    # Save model and feature names
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": list(X.columns),
        },
        MODEL_PATH,
    )
    print(f"Saved model to: {MODEL_PATH}")


if __name__ == "__main__":
    main()



