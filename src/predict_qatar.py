# src/predict_qatar.py

from pathlib import Path
import numpy as np
import pandas as pd
import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "ufc_qatar_v2.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_lite.joblib"


# -American odds and decimal odds conversion functions-


def american_to_payout(odds: float) -> float:
    """Net profit per $1 stake if the bet wins (American odds)."""
    if odds > 0:
        return odds / 100.0
    else:
        return 100.0 / -odds


def decimal_to_payout(dec: float) -> float:
    """Net profit per $1 stake if the bet wins (decimal odds)."""
    return dec - 1.0


# Main prediction plus EV calculation


def main() -> None:
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

    print(f"Loading upcoming fights from: {DATA_PATH}")
    # CSV no tabs
    df = pd.read_csv(DATA_PATH)
    print("Columns in ufc_qatar_v2.csv:", list(df.columns))

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns in ufc_qatar_v2.csv: {missing}")

    X = df[feature_cols]
    probs_red = model.predict_proba(X)[:, 1]
    probs_blue = 1.0 - probs_red

    df["prob_red_win"] = probs_red
    df["prob_blue_win"] = probs_blue

    # EV based on best price from DK/FD/PIN

    def row_ev(row, side: str) -> float:
        if side == "red":
            american_odds = [row["odds_red_DK"], row["odds_red_FD"]]
            decimal_odds = [row["odds_red_PIN"]]
            p_model = row["prob_red_win"]
        else:
            american_odds = [row["odds_blue_DK"], row["odds_blue_FD"]]
            decimal_odds = [row["odds_blue_PIN"]]
            p_model = row["prob_blue_win"]

        evs = []
        for o in american_odds:
            payout = american_to_payout(o)
            evs.append(p_model * payout - (1 - p_model) * 1.0)

        for d in decimal_odds:
            payout = decimal_to_payout(d)
            evs.append(p_model * payout - (1 - p_model) * 1.0)

        return max(evs)

    df["ev_red_per_$1"] = df.apply(lambda r: row_ev(r, "red"), axis=1)
    df["ev_blue_per_$1"] = df.apply(lambda r: row_ev(r, "blue"), axis=1)

    df["better_side"] = np.where(
        df["ev_red_per_$1"] > df["ev_blue_per_$1"], "Red", "Blue"
    )

    df["best_ev"] = df[["ev_red_per_$1", "ev_blue_per_$1"]].max(axis=1)
    df_sorted = df.sort_values("best_ev", ascending=False)

    out_path = PROJECT_ROOT / "data" / "ufc_qatar_v2_predictions.csv"
    df_sorted.to_csv(out_path, index=False)
    print(f"\nPredictions saved to: {out_path}\n")

    cols_to_show = [
        "red_fighter",
        "blue_fighter",
        "prob_red_win",
        "prob_blue_win",
        "ev_red_per_$1",
        "ev_blue_per_$1",
        "better_side",
        "best_ev",
    ]
    print(df_sorted[cols_to_show].to_string(index=False))


if __name__ == "__main__":
    main()
