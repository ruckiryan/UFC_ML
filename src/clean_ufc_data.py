# src/clean_ufc_data.py

from pathlib import Path
import pandas as pd


# ---------- Paths ----------
PROJECT_ROOT = Path(__file__).resolve().parents[1]   # C:\UFC_ML
INPUT_PATH = PROJECT_ROOT / "data" / "large_dataset.xlsx"
OUTPUT_PATH = PROJECT_ROOT / "data" / "ufc_features.csv"


def main():
    print(f"Loading raw data from: {INPUT_PATH}")
    df = pd.read_excel(INPUT_PATH)
    print(f"DONE Loaded shape: {df.shape}")

    # ---------- Filter to valid outcomes ----------
    # We only want fights where winner is clearly Red or Blue
    valid_winners = ["Red", "Blue"]
    before = len(df)
    df = df[df["winner"].isin(valid_winners)].copy()
    after = len(df)
    print(f"Filtered winner ∈ {valid_winners}: {before} → {after} rows")

    # ---------- Create binary target label ----------
    # win_red = 1 if red corner wins, 0 if blue corner wins
    df["win_red"] = df["winner"].apply(lambda x: 1 if x == "Red" else 0)

    # ---------- Identify diff feature columns ----------
    # We rely primarily on pre-engineered *_diff stats
    diff_cols = [c for c in df.columns if c.endswith("_diff")]
    print(f"Found {len(diff_cols)} diff feature columns")

    # ---------- Base feature columns ----------
    # - is_title_bout: 1 if title fight, else 0
    # - total_rounds: scheduled number of rounds (pre-fight info)
    # - weight_class: will be one-hot encoded
    base_cols = ["is_title_bout", "total_rounds", "weight_class"]

    missing_bases = [c for c in base_cols if c not in df.columns]
    if missing_bases:
        raise ValueError(f"Missing expected base columns: {missing_bases}")

    # ---------- Subset to features we want ----------
    feature_cols = base_cols + diff_cols
    keep_cols = feature_cols + ["win_red"]

    df_model = df[keep_cols].copy()
    print(f"Model frame initial shape: {df_model.shape}")

    # ---------- Drop rows with missing diff stats ----------
    # If a fight is missing key diff stats, it's safer to drop it.
    before_na = len(df_model)
    df_model = df_model.dropna(subset=diff_cols)
    after_na = len(df_model)
    print(f"Dropped rows with NaNs in diff columns: {before_na} → {after_na}")

    # ---------- One-hot encode weight_class ----------
    # Option C: keep weight class as categorical and one-hot encode it
    if df_model["weight_class"].isna().any():
        # If some weight_class are missing, decide whether to drop or fill
        # For now, drop rows with missing weight_class
        before_wc = len(df_model)
        df_model = df_model.dropna(subset=["weight_class"])
        after_wc = len(df_model)
        print(f"Dropped rows with missing weight_class: {before_wc} → {after_wc}")

    print("One-hot encoding weight_class...")
    df_model = pd.get_dummies(
        df_model,
        columns=["weight_class"],
        prefix="wc",
        drop_first=False  # keep all classes; model can handle the redundancy
    )

    # ---------- Final checks ----------
    # Separate features + target just for clarity (though we save them together)
    target_col = "win_red"
    X_cols = [c for c in df_model.columns if c != target_col]

    print(f"✅ Final model dataset shape: {df_model.shape}")
    print(f"   • Feature columns: {len(X_cols)}")
    print(f"   • Target column:   {target_col}")

    # ---------- Save to CSV ----------
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_model.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved cleaned, model-ready data to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
