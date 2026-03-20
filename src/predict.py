"""Unified UFC fight outcome predictor.

Usage:
    python -m src.predict --input data/ufc326.csv
    python -m src.predict --input data/ufc326.csv --model full --event "UFC 326"
    python -m src.predict --input data/ufc326_multibook.csv --odds-format multi-book

Odds formats:
  american   Single-book: expects columns american_odds_red, american_odds_blue
  multi-book Multi-book:  expects columns odds_red_DK, odds_red_FD, odds_red_PIN
                          and odds_blue_DK, odds_blue_FD, odds_blue_PIN
                          (DK/FD = American, PIN = decimal)

If --odds-format is omitted the format is auto-detected from the CSV columns.
"""

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.utils.odds import (
    american_to_implied_prob,
    american_to_payout,
    best_ev_multi_book,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODEL_PATHS = {
    "lite": PROJECT_ROOT / "models" / "ufc_xgb_lite.joblib",
    "full": PROJECT_ROOT / "models" / "ufc_xgb_model.joblib",
}

MULTI_BOOK_RED_COLS = ["odds_red_DK", "odds_red_FD", "odds_red_PIN"]
MULTI_BOOK_BLUE_COLS = ["odds_blue_DK", "odds_blue_FD", "odds_blue_PIN"]
AMERICAN_RED_COL = "american_odds_red"
AMERICAN_BLUE_COL = "american_odds_blue"


def detect_odds_format(df: pd.DataFrame) -> str:
    if AMERICAN_RED_COL in df.columns and AMERICAN_BLUE_COL in df.columns:
        return "american"
    if all(c in df.columns for c in MULTI_BOOK_RED_COLS + MULTI_BOOK_BLUE_COLS):
        return "multi-book"
    raise ValueError(
        "Cannot auto-detect odds format. Provide --odds-format or ensure the CSV has "
        f"either '{AMERICAN_RED_COL}'/'{AMERICAN_BLUE_COL}' columns (american) "
        f"or {MULTI_BOOK_RED_COLS + MULTI_BOOK_BLUE_COLS} columns (multi-book)."
    )


def _apply_american_ev(df: pd.DataFrame) -> pd.DataFrame:
    """Add EV columns for single-book American odds format."""
    df = df.copy()
    df["implied_prob_red"] = df[AMERICAN_RED_COL].apply(american_to_implied_prob)
    df["implied_prob_blue"] = df[AMERICAN_BLUE_COL].apply(american_to_implied_prob)

    red_payout = df[AMERICAN_RED_COL].apply(american_to_payout)
    blue_payout = df[AMERICAN_BLUE_COL].apply(american_to_payout)

    df["ev_red_per_$1"] = df["prob_red_win"] * red_payout - (1 - df["prob_red_win"])
    df["ev_blue_per_$1"] = df["prob_blue_win"] * blue_payout - (1 - df["prob_blue_win"])
    return df


def _apply_multi_book_ev(df: pd.DataFrame) -> pd.DataFrame:
    """Add EV columns for multi-book (DK/FD American + Pinnacle decimal) format."""
    df = df.copy()
    df["ev_red_per_$1"] = df.apply(
        lambda r: best_ev_multi_book(
            r["prob_red_win"],
            [r["odds_red_DK"], r["odds_red_FD"]],
            [r["odds_red_PIN"]],
        ),
        axis=1,
    )
    df["ev_blue_per_$1"] = df.apply(
        lambda r: best_ev_multi_book(
            r["prob_blue_win"],
            [r["odds_blue_DK"], r["odds_blue_FD"]],
            [r["odds_blue_PIN"]],
        ),
        axis=1,
    )
    return df


def run_predictions(
    input_path: Path,
    model_variant: str = "lite",
    odds_format: str | None = None,
    event_name: str | None = None,
    output_path: Path | None = None,
) -> pd.DataFrame:
    """Core prediction pipeline. Returns the sorted results DataFrame."""
    model_path = MODEL_PATHS[model_variant]
    print(f"Loading {model_variant} model from: {model_path}")
    bundle = joblib.load(model_path)
    model = bundle["model"]
    feature_cols = bundle["features"]

    print(f"Loading fights from: {input_path}")
    df = pd.read_csv(input_path)

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns in {input_path.name}: {missing}")

    df["prob_red_win"] = model.predict_proba(df[feature_cols])[:, 1]
    df["prob_blue_win"] = 1.0 - df["prob_red_win"]

    fmt = odds_format or detect_odds_format(df)
    print(f"Odds format: {fmt}")

    if fmt == "american":
        df = _apply_american_ev(df)
    else:
        df = _apply_multi_book_ev(df)

    df["better_side"] = np.where(
        df["ev_red_per_$1"] > df["ev_blue_per_$1"], "Red", "Blue"
    )
    df["best_ev"] = df[["ev_red_per_$1", "ev_blue_per_$1"]].max(axis=1)
    df_sorted = df.sort_values("best_ev", ascending=False)

    out = output_path or PROJECT_ROOT / "data" / f"{input_path.stem}_predictions.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df_sorted.to_csv(out, index=False)
    print(f"\nPredictions saved to: {out}")

    _print_results(df_sorted, event_name or input_path.stem)
    return df_sorted


def _print_results(df: pd.DataFrame, title: str) -> None:
    print(f"\n===== {title} Betting Model Results =====\n")
    for _, row in df.iterrows():
        print(f"{row['red_fighter']} vs {row['blue_fighter']}")
        print(f" - Red win probability:  {row['prob_red_win']:.2%}")
        print(f" - Blue win probability: {row['prob_blue_win']:.2%}")
        print(f" - EV per $1 (Red):      {row['ev_red_per_$1']:.3f}")
        print(f" - EV per $1 (Blue):     {row['ev_blue_per_$1']:.3f}")
        print(f" >>> Best Value Side:    {row['better_side']}")
        print(f" >>> Best EV:            {row['best_ev']:.3f}")
        print("-" * 45)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="UFC fight outcome predictor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input CSV (absolute or relative to project root)",
    )
    parser.add_argument(
        "--model",
        choices=["lite", "full"],
        default="lite",
        help="Model variant to use (default: lite)",
    )
    parser.add_argument(
        "--odds-format",
        choices=["american", "multi-book"],
        default=None,
        help="Odds format in CSV (auto-detected if omitted)",
    )
    parser.add_argument(
        "--event",
        default=None,
        help="Event name used in output label and file (defaults to input filename stem)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (defaults to data/<input_stem>_predictions.csv)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path

    output_path = Path(args.output) if args.output else None

    run_predictions(
        input_path=input_path,
        model_variant=args.model,
        odds_format=args.odds_format,
        event_name=args.event,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
