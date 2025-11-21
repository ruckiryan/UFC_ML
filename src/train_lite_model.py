# src/train_lite_model.py - adjusted for 20-features

from pathlib import Path
import pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, log_loss
import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "ufc_features.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_lite.joblib"


# 20-feature lite model
LITE_FEATURES = [
    "is_title_bout",
    "total_rounds",
    "sig_str_diff",
    "str_diff",
    "kd_diff",
    "sig_str_acc_diff",
    "str_acc_diff",
    "SLpM_total_diff",
    "SApM_total_diff",
    "str_def_total_diff",
    "td_diff",
    "td_acc_diff",
    "td_def_total_diff",
    "sub_att_diff",
    "sub_avg_diff",
    "ctrl_sec_diff",
    "age_diff",
    "reach_diff",
    "wins_total_diff",
    "losses_total_diff",
]


def main():
    print(f"Loading cleaned data from: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded shape: {df.shape}")

    target_col = "win_red"
    missing = [c for c in LITE_FEATURES + [target_col] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns in data: {missing}")

    # Subset to lite features + target
    df_lite = df[LITE_FEATURES + [target_col]].dropna()
    print(f"Lite dataset shape after dropping NaNs: {df_lite.shape}")

    X = df_lite[LITE_FEATURES]
    y = df_lite[target_col]

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    print("Training XGBoost LITE model...")
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

    p_te = model.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, p_te)
    ll = log_loss(y_te, p_te)

    print("✅ Lite model training complete")
    print(f"   ROC-AUC: {auc:.3f}")
    print(f"   LogLoss: {ll:.3f}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": LITE_FEATURES,
        },
        MODEL_PATH,
    )
    print(f"Saved lite model to: {MODEL_PATH}")


if __name__ == "__main__":
    main()
