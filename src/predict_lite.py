from pathlib import Path
import pandas as pd
import joblib
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "models" / "ufc_xgb_lite.joblib"
INPUT_PATH = PROJECT_ROOT / "data" / "ufc322_lite.csv"
OUTPUT_PATH = PROJECT_ROOT / "data" / "ufc322_lite_predictions.csv"


# TODO: REMOVE redundant odds conversion functions and import from src.utils.odds
# CHECK IF THESE ARE EXACTLY THE SAME AS IN src.utils.odds and if so, import them instead of redefining here.
def american_to_implied_prob(odds: float) -> float:
    if odds < 0:
        return (-odds) / ((-odds) + 100)
    else:
        return 100 / (odds + 100)


def american_to_profit_per_unit(odds: float) -> float:
    if odds < 0:
        return 100 / (-odds)
    else:
        return odds / 100.0


def main():
    print(f"Loading lite model from: {MODEL_PATH}")
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    feature_names = bundle["features"]

    print(f"Loading upcoming fights from: {INPUT_PATH}")
    df = pd.read_csv(INPUT_PATH)

    name_cols = ["red_fighter", "blue_fighter"]

    X = df[feature_names]

    print("Predicting red corner win probabilities...")
    probs_red = model.predict_proba(X)[:, 1]
    probs_blue = 1 - probs_red

    out = pd.DataFrame()
    out[name_cols] = df[name_cols]
    out["prob_red_win"] = probs_red
    out["prob_blue_win"] = probs_blue

    out["american_odds_red"] = df["american_odds_red"]
    out["american_odds_blue"] = df["american_odds_blue"]

    out["implied_prob_red"] = df["american_odds_red"].apply(american_to_implied_prob)
    out["implied_prob_blue"] = df["american_odds_blue"].apply(american_to_implied_prob)

    red_profit_unit = df["american_odds_red"].apply(american_to_profit_per_unit)
    blue_profit_unit = df["american_odds_blue"].apply(american_to_profit_per_unit)

    out["ev_red_per_$1"] = (out["prob_red_win"] * red_profit_unit) - (
        1 - out["prob_red_win"]
    )
    out["ev_blue_per_$1"] = (out["prob_blue_win"] * blue_profit_unit) - (
        1 - out["prob_blue_win"]
    )

    out["better_side"] = np.where(
        out["ev_red_per_$1"] > out["ev_blue_per_$1"], "Red", "Blue"
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False)
    print(f"\nPredictions saved to: {OUTPUT_PATH}")

    #  print results (INSIDE main)
    print("\n===== UFC 322 Betting Model Results =====\n")
    for _, row in out.iterrows():
        print(
            f"{row['red_fighter']} vs {row['blue_fighter']}\n"
            f" - Red win probability: {row['prob_red_win']:.2%}\n"
            f" - Blue win probability: {row['prob_blue_win']:.2%}\n"
            f" - EV per $1 (Red): {row['ev_red_per_$1']:.3f}\n"
            f" - EV per $1 (Blue): {row['ev_blue_per_$1']:.3f}\n"
            f" >>> Value Side: {row['better_side']}\n"
        )


if __name__ == "__main__":
    main()

