# src/train_lite_modelV2.py

from pathlib import Path
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, log_loss
from xgboost import XGBClassifier
import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "ufc_features.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_lite.joblib"


def main() -> None:
    print(f"Loading cleaned data from: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)

    # These column names MUST exist in ufc_features.csv
    feature_cols = [
        "is_title_bout",
        "total_rounds",
        "age_diff",
        "height_diff",
        "reach_diff",
        "SLpM_total_diff",
        "SApM_total_diff",
        "sig_str_acc_total_diff",
        "str_def_total_diff",
        "td_avg_diff",
        "td_acc_total_diff",
        "td_def_total_diff",
        "sub_avg_diff",
        "wins_total_diff",
        "losses_total_diff",
    ]

    # Target column created in clean_ufc_data.py
    target_col = "win_red"

    missing = [c for c in feature_cols + [target_col] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in ufc_features.csv: {missing}")

    X = df[feature_cols]
    y = df[target_col]

    print(f"Features shape: {X.shape}")
    print(f"Target shape:   {y.shape}")

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        stratify=y,
        random_state=42,
    )

    clf = XGBClassifier(
        n_estimators=600,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        n_jobs=4,
        random_state=42,
    )

    print("Training XGBoost LITE model...")
    clf.fit(X_train, y_train)

    p_test = clf.predict_proba(X_test)[:, 1]
    roc = roc_auc_score(y_test, p_test)
    ll = log_loss(y_test, p_test)

    print("✅ Lite model training complete")
    print(f"   ROC-AUC: {roc:.3f}")
    print(f"   LogLoss: {ll:.3f}")

    bundle = {"model": clf, "features": feature_cols}
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL_PATH)
    print(f"Saved lite model to: {MODEL_PATH}")


if __name__ == "__main__":
    main()
