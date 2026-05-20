from pathlib import Path
import pandas as pd
import joblib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "ufc_features.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_model.joblib"


def main():
    print(f" Loading cleaned data from: {DATA_PATH}")


df = pd.read_csv(DATA_PATH)

print(f"Loaded trained model from: {MODEL_PATH}")
bundle = joblib.load(MODEL_PATH)
model = bundle["model"]
feature_names = bundle["features"]

# Xg booost for feature importance ya hurd
importances = model.feature_importances_

# Dataframe
fi = (
    pd.DataFrame({"feature": feature_names, "importance": importances})
    .sort_values("importance", ascending=False)
    .reset_index(drop=True)
)

print("Top 20 most important features:")
print(fi.head(20).to_string(index=False))

# Averages by feature
fi["type"] = fi["feature"].apply(
    lambda x: "weight_class" if x.startswith("wc_") else "diff_stat"
)

print("Average importance by feature:")
print(fi.groupby("type")["importance"].mean().sort_values(ascending=False).to_string())

# Save full table yurrr

out_path = PROJECT_ROOT / "visuals" / "feature_importance.csv"
out_path.parent.mkdir(parents=True, exist_ok=True)
fi.to_csv(out_path, index=False)
print(f"Full Feature Importance Table saved to: {out_path}")

if __name__ == "__main__":
    main()
