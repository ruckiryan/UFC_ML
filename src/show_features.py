from pathlib import Path
import pandas as pd
import joblib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "ufc_features.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_model.joblib"

df = pd.read_csv(DATA_PATH)
bundle = joblib.load(MODEL_PATH)
feature_names = bundle["features"]

print(len(feature_names))
print(feature_names)
