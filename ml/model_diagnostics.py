import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from .price_predictor import PricePredictor


def _derive_event_window(
    db_path: Path, pre_event_days: int = 14, post_event_days: int = 30
) -> Optional[tuple[str, str]]:
    """
    Derive a global training window from the cs2_events table, matching the
    event-aware logic used in PricePredictor.train_model.
    """
    import sqlite3

    try:
        with sqlite3.connect(db_path) as conn:
            events_df = pd.read_sql_query(
                "SELECT MIN(start_date) AS min_start, MAX(end_date) AS max_end FROM cs2_events",
                conn,
                parse_dates=["min_start", "max_end"],
            )
        if (
            events_df.empty
            or pd.isna(events_df["min_start"].iloc[0])
            or pd.isna(events_df["max_end"].iloc[0])
        ):
            return None
        min_start = events_df["min_start"].iloc[0].normalize()
        max_end = events_df["max_end"].iloc[0].normalize()
        from_date = (min_start - pd.Timedelta(days=pre_event_days)).date().isoformat()
        to_date = (max_end + pd.Timedelta(days=post_event_days)).date().isoformat()
        return from_date, to_date
    except Exception:
        return None


def evaluate_model(
    model_dir: str,
    game_id: str = "730",
    max_items: Optional[int] = None,
    use_event_window: bool = True,
    pre_event_days: int = 14,
    post_event_days: int = 30,
    output_dir: Optional[str] = None,
) -> None:
    """
    Load a trained model from `model_dir`, rebuild the feature matrix using the
    current PricePredictor data pipeline, and generate diagnostic plots:

    - y_true vs y_pred scatter
    - Histogram of true vs predicted returns
    - Top feature importances bar chart
    """
    project_root = Path(__file__).resolve().parents[1]
    db_path = project_root / "data" / "market_data.db"

    predictor = PricePredictor(db_path=str(db_path))

    if not predictor.load_models(path=model_dir):
        raise RuntimeError(f"No models found in {model_dir} for evaluation.")

    # Derive time window if requested
    from_date = None
    to_date = None
    if use_event_window:
        window = _derive_event_window(db_path)
        if window is not None:
            from_date, to_date = window

    # Rebuild data using the same pipeline as training
    X, y, item_names, timestamps = predictor.prepare_data(
        game_id,
        max_items=max_items,
        from_date=from_date,
        to_date=to_date,
    )
    if X is None or timestamps is None:
        raise RuntimeError("No data available for diagnostics.")

    sort_idx = np.argsort(timestamps)
    X = X[sort_idx]
    y = y[sort_idx]

    n_samples = len(X)
    split_idx = int(n_samples * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    scaler = predictor.scalers[game_id]
    model = predictor.models[game_id]

    X_train_scaled = scaler.transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    y_pred = model.predict(X_test_scaled)

    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    print("=== Diagnostics ===")
    print(f"Samples (total): {n_samples}")
    print(f"Samples (train/test): {len(X_train)}/{len(X_test)}")
    print(f"MSE (returns): {mse:.6f}")
    print(f"RMSE (returns): {rmse:.6f}")
    print(f"MAE (returns): {mae:.6f}")
    print(f"R2 (returns): {r2:.4f}")

    if output_dir is None:
        output_dir = os.path.join(model_dir, "diagnostics")
    os.makedirs(output_dir, exist_ok=True)

    # 1. y_true vs y_pred scatter
    plt.figure(figsize=(6, 6))
    plt.scatter(y_test, y_pred, s=5, alpha=0.3)
    lims = [
        min(np.min(y_test), np.min(y_pred)),
        max(np.max(y_test), np.max(y_pred)),
    ]
    plt.plot(lims, lims, "r--", label="Ideal")
    plt.xlabel("True return")
    plt.ylabel("Predicted return")
    plt.title(f"y_true vs y_pred (game {game_id})")
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"scatter_y_true_vs_pred_{game_id}.png"))
    plt.close()

    # 2. Histogram of true vs predicted returns
    plt.figure(figsize=(8, 4))
    bins = np.linspace(
        np.percentile(y_test, 1),
        np.percentile(y_test, 99),
        50,
    )
    plt.hist(y_test, bins=bins, alpha=0.5, label="True", density=True)
    plt.hist(y_pred, bins=bins, alpha=0.5, label="Predicted", density=True)
    plt.xlabel("Return")
    plt.ylabel("Density")
    plt.title(f"Distribution of returns (true vs predicted, game {game_id})")
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"hist_returns_true_vs_pred_{game_id}.png"))
    plt.close()

    # 3. Top feature importances
    importances = model.feature_importances_
    # Reuse the feature_names from PricePredictor for consistency
    base_feature_names = [
        "price",
        "price_ma7",
        "price_ma30",
        "price_std7",
        "volume_ma7",
        "ret_7",
        "ret_30",
        "day_of_week",
        "month",
        "num_events",
        "has_event_today",
        "is_major_today",
        "max_stars_prev_7d",
        "max_stars_prev_30d",
        "type_weapon_skin",
        "type_sticker",
        "type_case",
        "type_agent",
        "type_gloves",
        "type_knife",
        "type_other",
        "is_weapon_skin",
        "condition_quality",
        "is_stattrak",
        "is_souvenir",
        "has_sticker",
        "is_case",
        "is_sticker",
        "is_agent",
        "is_gloves",
        "is_knife",
    ]
    feature_names = [
        base_feature_names[i] if i < len(base_feature_names) else f"feature_{i}"
        for i in range(len(importances))
    ]
    top_idx = np.argsort(importances)[-10:][::-1]
    plt.figure(figsize=(8, 4))
    plt.barh(
        [feature_names[i] for i in top_idx],
        [importances[i] for i in top_idx],
    )
    plt.gca().invert_yaxis()
    plt.xlabel("Importance")
    plt.title(f"Top 10 feature importances (game {game_id})")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"feature_importances_top10_{game_id}.png"))
    plt.close()


def main() -> None:
    """
    Example CLI entry point:

        python -m ml.model_diagnostics --model-dir models_events_2023_2024 --game-id 730
    """
    import argparse

    parser = argparse.ArgumentParser(description="Run diagnostics for a trained price model.")
    parser.add_argument("--model-dir", type=str, default="models", help="Directory containing saved model/scaler.")
    parser.add_argument("--game-id", type=str, default="730", help="Game ID to evaluate.")
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Optional max_items limit for diagnostics data preparation.",
    )
    parser.add_argument(
        "--no-event-window",
        action="store_true",
        help="Disable event-derived time window; use full available history instead.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Optional directory to write plots into (defaults to <model-dir>/diagnostics).",
    )

    args = parser.parse_args()

    evaluate_model(
        model_dir=args.model_dir,
        game_id=args.game_id,
        max_items=args.max_items,
        use_event_window=not args.no_event_window,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()

