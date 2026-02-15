#src/predict_ufc325.py VERSION 2 MODEL

from pathlib import Path
import numpy as np
import pandas as pd
import joblib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "ufc325.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_lite.joblib"  # your v2-lite trained model

def american_to_payout(odds: float) -> float:
    # Net profit per $1 stake if the bet wins
    if odds > 0:
        return odds / 100.0
    return 100.0 / -odds

def decimal_to_payout(dec: float) -> float:
    # Net profit per $1 stake if the bet wins
    return dec - 1.0

def main():
    print(f"Loading model from: {MODEL_PATH}")
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]

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

    print(f"Loading UFC 325 fights from: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
   

    # sanity check
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns in ufc324.csv: {missing}")

    X = df[feature_cols]
    prob_red = model.predict_proba(X)[:, 1]
    prob_blue = 1.0 - prob_red

    df["prob_red_win"] = prob_red
    df["prob_blue_win"] = prob_blue

    def best_ev(row, side: str) -> float:
        if side == "red":
            p = row["prob_red_win"]
            amer = [row["odds_red_DK"], row["odds_red_FD"]]
            dec = [row["odds_red_PIN"]]
        else:
            p = row["prob_blue_win"]
            amer = [row["odds_blue_DK"], row["odds_blue_FD"]]
            dec = [row["odds_blue_PIN"]]

        evs = []
        for o in amer:
            payout = american_to_payout(o)
            evs.append(p * payout - (1 - p) * 1.0)

        for d in dec:
            payout = decimal_to_payout(d)
            evs.append(p * payout - (1 - p) * 1.0)

        return max(evs)

    df["ev_red_per_$1"] = df.apply(lambda r: best_ev(r, "red"), axis=1)
    df["ev_blue_per_$1"] = df.apply(lambda r: best_ev(r, "blue"), axis=1)

    df["better_side"] = np.where(df["ev_red_per_$1"] > df["ev_blue_per_$1"], "Red", "Blue")
    df["best_ev"] = df[["ev_red_per_$1", "ev_blue_per_$1"]].max(axis=1)

    df_sorted = df.sort_values("best_ev", ascending=False)

    out_path = PROJECT_ROOT / "data" / "ufc325_predictions.csv"
    df_sorted.to_csv(out_path, index=False)

    print(f"\nPredictions saved to: {out_path}\n")
    
    print("\n===== UFC 325 Betting Model Results =====\n")

    for _, row in df_sorted.iterrows():
        print(f"{row['red_fighter']} vs {row['blue_fighter']}")
        print(f" - Red win probability:  {row['prob_red_win']:.2%}")
        print(f" - Blue win probability: {row['prob_blue_win']:.2%}")
        print(f" - EV per $1 (Red):      {row['ev_red_per_$1']:.3f}")
        print(f" - EV per $1 (Blue):     {row['ev_blue_per_$1']:.3f}")
        print(f" >>> Best Value Side:    {row['better_side']}")
        print(f" >>> Best EV:            {row['best_ev']:.3f}")
        print("-" * 45)


if __name__ == "__main__":
    main()


    