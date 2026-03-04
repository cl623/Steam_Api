"""
Run model comparison (RF vs GB), print the metrics table, and generate
common regression/comparison plots.

Usage:
  python scripts/run_comparison_with_plots.py
  python scripts/run_comparison_with_plots.py --max-items 300 --out-dir comparison_results
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on path
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

from ml.model_comparison import compare_models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def plot_metrics_bars(metrics_df: pd.DataFrame, out_path: Path) -> None:
    """Bar chart of MSE, RMSE, MAE, R², MAPE by model."""
    metrics_df = metrics_df.copy()
    metrics_df["model"] = metrics_df["model"].str.upper()
    cols = ["mse", "rmse", "mae", "r2", "mape_pct"]
    labels = ["MSE", "RMSE", "MAE", "R²", "MAPE (%)"]
    fig, axes = plt.subplots(2, 3, figsize=(12, 8))
    axes = axes.flatten()
    x = np.arange(len(metrics_df))
    width = 0.35
    colors = ["#2ecc71", "#3498db"]
    for i, (col, label) in enumerate(zip(cols, labels)):
        ax = axes[i]
        bars = ax.bar(x - width / 2, metrics_df[col], width, color=colors[: len(metrics_df)], tick_label=metrics_df["model"])
        ax.set_ylabel(label)
        ax.set_title(label)
        for b in bars:
            h = b.get_height()
            ax.text(b.get_x() + b.get_width() / 2, h, f"{h:.3g}", ha="center", va="bottom", fontsize=8)
    axes[-1].axis("off")
    fig.suptitle("Model comparison – test set metrics (returns)", fontsize=12)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_actual_vs_predicted(
    y_test: np.ndarray, preds_dict: dict[str, np.ndarray], out_path: Path
) -> None:
    """Scatter: actual vs predicted returns for each model (2 panels)."""
    models = list(preds_dict.keys())
    n = len(models)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 5))
    if n == 1:
        axes = [axes]
    for ax, (name, pred) in zip(axes, preds_dict.items()):
        ax.scatter(y_test, pred, alpha=0.3, s=8, label=name.upper())
        lims = [
            min(y_test.min(), pred.min()),
            max(y_test.max(), pred.max()),
        ]
        ax.plot(lims, lims, "k--", alpha=0.5, label="Perfect")
        ax.set_xlabel("Actual return")
        ax.set_ylabel("Predicted return")
        ax.set_title(f"{name.upper()}: Actual vs Predicted")
        ax.legend()
        ax.set_aspect("equal", adjustable="box")
    fig.suptitle("Actual vs predicted returns (test set)", fontsize=12)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_residuals_histogram(
    y_test: np.ndarray, preds_dict: dict[str, np.ndarray], out_path: Path
) -> None:
    """Histogram of residuals (y_true - y_pred) per model."""
    fig, axes = plt.subplots(1, len(preds_dict), figsize=(5 * len(preds_dict), 4))
    if len(preds_dict) == 1:
        axes = [axes]
    for ax, (name, pred) in zip(axes, preds_dict.items()):
        res = y_test - pred
        ax.hist(res, bins=50, alpha=0.7, label=name.upper(), edgecolor="black", linewidth=0.3)
        ax.axvline(0, color="k", linestyle="--")
        ax.set_xlabel("Residual (actual - predicted)")
        ax.set_ylabel("Count")
        ax.set_title(f"{name.upper()} residuals")
        ax.legend()
    fig.suptitle("Residual distribution (test set)", fontsize=12)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_residuals_vs_predicted(
    y_test: np.ndarray, preds_dict: dict[str, np.ndarray], out_path: Path
) -> None:
    """Residuals vs predicted (check for heteroscedasticity)."""
    fig, axes = plt.subplots(1, len(preds_dict), figsize=(5 * len(preds_dict), 4))
    if len(preds_dict) == 1:
        axes = [axes]
    for ax, (name, pred) in zip(axes, preds_dict.items()):
        res = y_test - pred
        ax.scatter(pred, res, alpha=0.3, s=8)
        ax.axhline(0, color="k", linestyle="--")
        ax.set_xlabel("Predicted return")
        ax.set_ylabel("Residual")
        ax.set_title(f"{name.upper()}: Residual vs Predicted")
    fig.suptitle("Residuals vs predicted (heteroscedasticity check)", fontsize=12)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Run comparison and plot metrics/diagnostics.")
    parser.add_argument("--game-id", type=str, default="730")
    parser.add_argument("--max-items", type=int, default=None, help="Cap number of items (faster run)")
    parser.add_argument("--no-event-window", action="store_true", help="Disable event window")
    parser.add_argument("--out-dir", type=str, default="comparison_output", help="Output directory for plots")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Running comparison with predictions for plotting...")
    metrics_df, y_test, preds_dict = compare_models(
        game_id=args.game_id,
        max_items=args.max_items,
        use_event_window=not args.no_event_window,
        return_predictions=True,
    )

    # Print table
    print("\n" + "=" * 60)
    print("Model comparison (test set, returns)")
    print("=" * 60)
    print(metrics_df.to_string(index=False))
    best = metrics_df.loc[metrics_df["r2"].idxmax(), "model"]
    print("\nBest by R²:", best)
    print("=" * 60 + "\n")

    # Plots
    logging.info("Writing plots to %s", out_dir)
    plot_metrics_bars(metrics_df, out_dir / "metrics_by_model.png")
    plot_actual_vs_predicted(y_test, preds_dict, out_dir / "actual_vs_predicted.png")
    plot_residuals_histogram(y_test, preds_dict, out_dir / "residuals_histogram.png")
    plot_residuals_vs_predicted(y_test, preds_dict, out_dir / "residuals_vs_predicted.png")

    # Save metrics CSV
    metrics_path = out_dir / "metrics.csv"
    metrics_df.to_csv(metrics_path, index=False)
    logging.info("Saved %s", metrics_path)
    logging.info("Done. Plots: %s", list(out_dir.glob("*.png")))


if __name__ == "__main__":
    main()
