"""
Milestone 3: Compare RF vs GB on the same data split and optionally tune GB.

Usage:
  python -m ml.model_comparison --game-id 730 --max-items 500 --use-event-window
  python -m ml.model_comparison --game-id 730 --tune-gb --n-jobs 2
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.preprocessing import StandardScaler

from .price_predictor import PricePredictor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def _mape_on_returns(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-8) -> float:
    """Mean absolute percentage error on returns; skip near-zero true returns."""
    mask = np.abs(y_true) > eps
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)


def compare_models(
    game_id: str = "730",
    max_items: Optional[int] = None,
    use_event_window: bool = True,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    pre_event_days: int = 14,
    post_event_days: int = 30,
    test_fraction: float = 0.2,
    return_predictions: bool = False,
):
    """
    Prepare data once, train both RF and GB on the same chronological split,
    and return a comparison table of metrics.

    If return_predictions is True, returns (metrics_df, y_test, preds_dict)
    where preds_dict has keys "rf" and "gb" with arrays of test-set predictions.
    Otherwise returns only metrics_df.
    """
    predictor = PricePredictor()
    if use_event_window and (from_date is None or to_date is None):
        try:
            import sqlite3
            with sqlite3.connect(predictor.db_path) as conn:
                events_df = pd.read_sql_query(
                    "SELECT MIN(start_date) AS min_start, MAX(end_date) AS max_end FROM cs2_events",
                    conn,
                    parse_dates=["min_start", "max_end"],
                )
            if not events_df.empty and pd.notna(events_df["min_start"].iloc[0]) and pd.notna(events_df["max_end"].iloc[0]):
                min_start = events_df["min_start"].iloc[0].normalize()
                max_end = events_df["max_end"].iloc[0].normalize()
                from_date = (min_start - pd.Timedelta(days=pre_event_days)).date().isoformat()
                to_date = (max_end + pd.Timedelta(days=post_event_days)).date().isoformat()
        except Exception as e:
            logging.warning("Could not derive event window: %s", e)

    X, y, _, timestamps = predictor.prepare_data(
        game_id,
        max_items=max_items,
        from_date=from_date,
        to_date=to_date,
    )
    if X is None or timestamps is None:
        raise RuntimeError("No data for comparison.")

    sort_idx = np.argsort(timestamps)
    X = X[sort_idx]
    y = y[sort_idx]
    n = len(X)
    split_idx = int(n * (1.0 - test_fraction))
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    results = []
    preds_dict: Dict[str, np.ndarray] = {}

    for name, model in [
        ("rf", RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)),
        ("gb", HistGradientBoostingRegressor(max_depth=6, learning_rate=0.05, max_iter=300, random_state=42, loss="absolute_error")),
    ]:
        model.fit(X_train_s, y_train)
        pred = model.predict(X_test_s)
        if return_predictions:
            preds_dict[name] = pred
        results.append({
            "model": name,
            "mse": mean_squared_error(y_test, pred),
            "rmse": np.sqrt(mean_squared_error(y_test, pred)),
            "mae": mean_absolute_error(y_test, pred),
            "r2": r2_score(y_test, pred),
            "mape_pct": _mape_on_returns(y_test, pred),
        })

    df = pd.DataFrame(results)
    if return_predictions:
        return df, y_test, preds_dict
    return df


def tune_gb(
    game_id: str = "730",
    max_items: Optional[int] = None,
    use_event_window: bool = True,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    pre_event_days: int = 14,
    post_event_days: int = 30,
    n_splits: int = 3,
    n_jobs: int = -1,
):
    """
    Run a small grid search for HistGradientBoostingRegressor using
    TimeSeriesSplit to respect time order.
    """
    predictor = PricePredictor()
    if use_event_window and (from_date is None or to_date is None):
        try:
            import sqlite3
            with sqlite3.connect(predictor.db_path) as conn:
                events_df = pd.read_sql_query(
                    "SELECT MIN(start_date) AS min_start, MAX(end_date) AS max_end FROM cs2_events",
                    conn,
                    parse_dates=["min_start", "max_end"],
                )
            if not events_df.empty and pd.notna(events_df["min_start"].iloc[0]) and pd.notna(events_df["max_end"].iloc[0]):
                min_start = events_df["min_start"].iloc[0].normalize()
                max_end = events_df["max_end"].iloc[0].normalize()
                from_date = (min_start - pd.Timedelta(days=pre_event_days)).date().isoformat()
                to_date = (max_end + pd.Timedelta(days=post_event_days)).date().isoformat()
        except Exception as e:
            logging.warning("Could not derive event window: %s", e)

    X, y, _, timestamps = predictor.prepare_data(
        game_id,
        max_items=max_items,
        from_date=from_date,
        to_date=to_date,
    )
    if X is None or timestamps is None:
        raise RuntimeError("No data for tuning.")

    sort_idx = np.argsort(timestamps)
    X = X[sort_idx]
    y = y[sort_idx]

    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)

    param_grid = {
        "max_depth": [4, 6, 8],
        "learning_rate": [0.03, 0.05, 0.1],
        "max_iter": [200, 300, 500],
    }
    cv = TimeSeriesSplit(n_splits=n_splits)
    gb = HistGradientBoostingRegressor(random_state=42)
    search = GridSearchCV(gb, param_grid, cv=cv, scoring="neg_mean_squared_error", n_jobs=n_jobs, verbose=1)
    search.fit(X_s, y)

    return {
        "best_params": search.best_params_,
        "best_score": -search.best_score_,
        "cv_results": search.cv_results_,
    }


def main():
    parser = argparse.ArgumentParser(description="Compare RF vs GB and optionally tune GB.")
    parser.add_argument("--game-id", type=str, default="730")
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--no-event-window", action="store_true", help="Disable event window")
    parser.add_argument("--tune-gb", action="store_true", help="Run grid search for GB")
    parser.add_argument("--n-jobs", type=int, default=-1)
    args = parser.parse_args()

    if args.tune_gb:
        logging.info("Running GB hyperparameter tuning (TimeSeriesSplit)...")
        out = tune_gb(
            game_id=args.game_id,
            max_items=args.max_items,
            use_event_window=not args.no_event_window,
            n_jobs=args.n_jobs,
        )
        logging.info("Best params: %s", out["best_params"])
        logging.info("Best CV MSE (returns): %s", out["best_score"])
        return

    logging.info("Comparing RF vs GB on same chronological split...")
    df = compare_models(
        game_id=args.game_id,
        max_items=args.max_items,
        use_event_window=not args.no_event_window,
    )
    print("\n=== Model comparison (test set, returns) ===")
    print(df.to_string(index=False))
    best = df.loc[df["r2"].idxmax(), "model"]
    print("\nBest by R2:", best)


if __name__ == "__main__":
    main()
