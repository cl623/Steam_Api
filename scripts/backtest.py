"""
Backtesting script: simulate a $100 trading bot using model predictions
on historical Steam market data over a 3-month test window.

Strategy:
  Each week the bot evaluates all items, picks the top K with the highest
  predicted 7-day return (above the break-even threshold after fees), splits
  its cash equally among them, and sells 7 days later at actual market prices.

Usage:
  python -m scripts.backtest
  python -m scripts.backtest --starting-balance 100 --fee-pct 15 --top-k 5
  python -m scripts.backtest --model rf
  python -m scripts.backtest --model gb
  python -m scripts.backtest --model all
  python -m scripts.backtest --demo          # run with synthetic data
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

from ml.price_predictor import PricePredictor
from ml.feature_extractor import ItemFeatureExtractor

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

MODELS = {
    "rf": (
        "Random Forest",
        lambda: RandomForestRegressor(
            n_estimators=200, random_state=42, n_jobs=-1
        ),
    ),
    "gb": (
        "Gradient Boosting",
        lambda: HistGradientBoostingRegressor(
            max_depth=6, learning_rate=0.05, max_iter=300, random_state=42
        ),
    ),
}

FEATURE_NAMES = [
    "price", "price_ma7", "price_ma30", "price_std7", "volume_ma7",
    "ret_7", "ret_30", "day_of_week", "month",
    "num_events", "has_event_today", "is_major_today",
    "max_stars_prev_7d", "max_stars_prev_30d", "price_band", "volume_band",
    "type_weapon_skin", "type_sticker", "type_case", "type_agent",
    "type_gloves", "type_knife", "type_other", "is_weapon_skin",
    "condition_quality", "is_stattrak", "is_souvenir", "has_sticker",
    "is_case", "is_sticker", "is_agent", "is_gloves", "is_knife",
]


DEMO_ITEMS = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
    "M4A4 | Howl (Minimal Wear)",
    "Operation Breakout Weapon Case",
    "Sticker | Katowice 2014 (Holo)",
    "Desert Eagle | Blaze (Factory New)",
    "USP-S | Kill Confirmed (Minimal Wear)",
    "Glock-18 | Fade (Factory New)",
    "M4A1-S | Hyper Beast (Field-Tested)",
    "AK-47 | Fire Serpent (Minimal Wear)",
    "AWP | Dragon Lore (Field-Tested)",
    "Sticker | Crown (Foil)",
    "Falchion Case",
    "Shadow Case",
    "Chroma 2 Case",
    "P90 | Asiimov (Minimal Wear)",
    "SSG 08 | Blood in the Water (Factory New)",
    "MAC-10 | Neon Rider (Factory New)",
    "AK-47 | Vulcan (Minimal Wear)",
    "M4A4 | Asiimov (Field-Tested)",
]


def _generate_demo_data(
    n_items: int = 20,
    history_days: int = 270,
    prediction_days: int = 7,
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray, list, np.ndarray]:
    """
    Generate synthetic data that mimics the structure of real Steam market data
    for demonstration purposes. Returns (X, y, item_names, timestamps) in the
    same format as PricePredictor.prepare_data().

    Items have varied dynamics (trending, mean-reverting, event-driven) so the
    ML models have actual signal to learn from.
    """
    rng = np.random.RandomState(seed)
    extractor = ItemFeatureExtractor()
    items = DEMO_ITEMS[:n_items]

    base_prices = rng.lognormal(mean=1.5, sigma=1.2, size=n_items).clip(0.03, 500)
    base_volumes = rng.lognormal(mean=3.0, sigma=1.0, size=n_items).clip(2, 5000).astype(int)

    archetypes = rng.choice(
        ["uptrend", "downtrend", "mean_revert", "volatile", "stable"],
        size=n_items,
    )

    start_date = pd.Timestamp("2025-06-01")
    all_X, all_y, all_names, all_ts = [], [], [], []

    pp = PricePredictor.__new__(PricePredictor)

    for i, item_name in enumerate(items):
        price = base_prices[i]
        vol = base_volumes[i]
        arch = archetypes[i]
        prices = [price]

        mean_price = price
        for d in range(1, history_days):
            if arch == "uptrend":
                drift = 0.003
                noise = 0.025
            elif arch == "downtrend":
                drift = -0.002
                noise = 0.025
            elif arch == "mean_revert":
                drift = 0.15 * (mean_price - price) / mean_price
                noise = 0.03
            elif arch == "volatile":
                drift = 0.0005
                noise = 0.06
            else:
                drift = 0.0001
                noise = 0.012

            # periodic event spikes (~every 60 days)
            if d % 60 < 5:
                drift += 0.01
            elif d % 60 < 10:
                drift -= 0.005

            shock = rng.normal(0, noise)
            price = max(0.03, price * (1 + drift + shock))
            prices.append(price)

        prices = np.array(prices)
        volumes = (vol * rng.lognormal(0, 0.3, size=history_days)).clip(1).astype(int)

        item_feats = extractor.get_feature_vector(item_name)
        if item_feats["type_weapon_skin"] == 1.0:
            item_type = "weapon_skin"
        elif item_feats["type_sticker"] == 1.0:
            item_type = "sticker"
        elif item_feats["type_gloves"] == 1.0:
            item_type = "gloves"
        elif item_feats["type_knife"] == 1.0:
            item_type = "knife"
        else:
            item_type = "other"

        for d in range(30, history_days - prediction_days):
            ts = start_date + pd.Timedelta(days=d)
            p = prices[d]
            fp = prices[d + prediction_days]
            ret = (fp - p) / p if p > 0 else 0.0

            w7 = prices[max(0, d - 6):d + 1]
            w30 = prices[max(0, d - 29):d + 1]
            v7 = volumes[max(0, d - 6):d + 1]

            features = [
                p,
                float(np.mean(w7)),
                float(np.mean(w30)),
                float(np.std(w7)) if len(w7) > 1 else 0.0,
                float(np.mean(v7)),
                float((p - prices[max(0, d - 7)]) / prices[max(0, d - 7)]) if prices[max(0, d - 7)] > 0 else 0.0,
                float((p - prices[max(0, d - 30)]) / prices[max(0, d - 30)]) if prices[max(0, d - 30)] > 0 else 0.0,
                ts.dayofweek,
                ts.month,
                0.0, 0.0, 0.0, 0.0, 0.0,  # event features
                pp._get_price_band(p, item_type),
                pp._get_volume_band(float(np.mean(v7))),
                item_feats["type_weapon_skin"],
                item_feats["type_sticker"],
                item_feats["type_case"],
                item_feats["type_agent"],
                item_feats["type_gloves"],
                item_feats["type_knife"],
                item_feats["type_other"],
                item_feats["is_weapon_skin"],
                item_feats["condition_quality"],
                item_feats["is_stattrak"],
                item_feats["is_souvenir"],
                item_feats["has_sticker"],
                item_feats["is_case"],
                item_feats["is_sticker"],
                item_feats["is_agent"],
                item_feats["is_gloves"],
                item_feats["is_knife"],
            ]
            all_X.append(features)
            all_y.append(float(np.clip(ret, -3.0, 3.0)))
            all_names.append(item_name)
            all_ts.append(ts)

    return (
        np.array(all_X),
        np.array(all_y),
        all_names,
        np.array(all_ts),
    )


def _sparkline(values: List[float], width: int = 40) -> str:
    """Tiny ASCII sparkline of a numeric series."""
    if len(values) < 2:
        return ""
    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1.0
    chars = " ._-=+*#@"
    return "".join(chars[min(int((v - mn) / rng * (len(chars) - 1)), len(chars) - 1)] for v in values)


def _max_drawdown(balances: List[float]) -> float:
    """Maximum peak-to-trough drawdown as a percentage."""
    peak = balances[0]
    max_dd = 0.0
    for b in balances:
        if b > peak:
            peak = b
        dd = (peak - b) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


COLORS = {
    "rf": "#2ecc71",
    "gb": "#3498db",
    "fee": "#e74c3c",
    "nofee": "#27ae60",
    "neutral": "#95a5a6",
    "bg": "#f8f9fa",
}


def _generate_plots(
    plot_data: Dict[str, dict],
    y_test: np.ndarray,
    test_dates: pd.Series,
    test_start: pd.Timestamp,
    starting_balance: float,
    fee_pct: float,
    out_dir: Path,
) -> bool:
    """Generate all backtest analysis plots and save to *out_dir*.
    Returns True if plots were created, False otherwise."""
    if not HAS_MPL:
        logging.warning("matplotlib not installed -- skipping plots. Run: pip install matplotlib")
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    model_keys = list(plot_data.keys())

    # ── 1. Equity Curves (all models, with & without fees) ──────────
    fig, ax = plt.subplots(figsize=(12, 5))
    for key in model_keys:
        d = plot_data[key]
        weeks = range(len(d["bal_curve"]))
        ax.plot(weeks, d["bal_curve"], linewidth=2,
                color=COLORS.get(key, "#333"), label=f"{d['name']} (w/ {fee_pct:.0f}% fee)")
        ax.plot(weeks, d["bal_curve_nf"], linewidth=2, linestyle="--",
                color=COLORS.get(key, "#333"), alpha=0.5, label=f"{d['name']} (no fee)")
    ax.axhline(starting_balance, color=COLORS["neutral"], linestyle=":", alpha=0.6, label="Starting $")
    ax.set_xlabel("Trading Week")
    ax.set_ylabel("Portfolio Value ($)")
    ax.set_title("Equity Curve: Portfolio Value Over Time")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "1_equity_curves.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 2. Predicted vs Actual Returns (scatter per model) ──────────
    n_models = len(model_keys)
    fig, axes = plt.subplots(1, n_models, figsize=(6 * n_models, 5.5), squeeze=False)
    for i, key in enumerate(model_keys):
        d = plot_data[key]
        ax = axes[0, i]
        pred = d["pred_all"]
        actual = y_test
        ax.scatter(actual * 100, pred * 100, alpha=0.15, s=6,
                   color=COLORS.get(key, "#333"), rasterized=True)
        lo = min(actual.min(), pred.min()) * 100
        hi = max(actual.max(), pred.max()) * 100
        ax.plot([lo, hi], [lo, hi], "k--", alpha=0.5, linewidth=1, label="Perfect prediction")
        ax.set_xlabel("Actual 7-day return (%)")
        ax.set_ylabel("Predicted 7-day return (%)")
        r2 = r2_score(actual, pred)
        mae = mean_absolute_error(actual, pred)
        ax.set_title(f"{d['name']}\nR\u00b2={r2:.4f}  MAE={mae:.4f}")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_aspect("equal", adjustable="box")
    fig.suptitle("Predicted vs Actual Returns (full test set)", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "2_predicted_vs_actual.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 3. Direction Accuracy Breakdown (stacked bar per model) ─────
    fig, axes = plt.subplots(1, n_models, figsize=(5 * n_models, 4.5), squeeze=False)
    for i, key in enumerate(model_keys):
        d = plot_data[key]
        pred = d["pred_all"]
        actual = y_test
        tp = int(np.sum((pred > 0) & (actual > 0)))
        tn = int(np.sum((pred <= 0) & (actual <= 0)))
        fp = int(np.sum((pred > 0) & (actual <= 0)))
        fn = int(np.sum((pred <= 0) & (actual > 0)))
        total = tp + tn + fp + fn
        ax = axes[0, i]
        labels = ["True Up\n(correct)", "True Down\n(correct)", "False Up\n(wrong)", "False Down\n(wrong)"]
        vals = [tp, tn, fp, fn]
        colors_bar = ["#2ecc71", "#27ae60", "#e74c3c", "#c0392b"]
        bars = ax.bar(labels, vals, color=colors_bar, edgecolor="white", linewidth=0.8)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + total * 0.01,
                    f"{v}\n({v / total * 100:.1f}%)", ha="center", va="bottom", fontsize=8)
        acc = (tp + tn) / total * 100
        ax.set_title(f"{d['name']}\nDirection Accuracy: {acc:.1f}%")
        ax.set_ylabel("Count")
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Direction Accuracy Breakdown", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "3_direction_accuracy.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 4. Return Distribution: Predicted vs Actual (overlaid hist) ─
    fig, axes = plt.subplots(1, n_models, figsize=(6 * n_models, 4.5), squeeze=False)
    for i, key in enumerate(model_keys):
        d = plot_data[key]
        ax = axes[0, i]
        bins = np.linspace(
            min(y_test.min(), d["pred_all"].min()) * 100,
            max(y_test.max(), d["pred_all"].max()) * 100,
            60,
        )
        ax.hist(y_test * 100, bins=bins, alpha=0.5, color=COLORS["neutral"],
                label="Actual", edgecolor="white", linewidth=0.3)
        ax.hist(d["pred_all"] * 100, bins=bins, alpha=0.5, color=COLORS.get(key, "#333"),
                label="Predicted", edgecolor="white", linewidth=0.3)
        ax.axvline(0, color="k", linestyle="--", alpha=0.4)
        ax.set_xlabel("7-day return (%)")
        ax.set_ylabel("Frequency")
        ax.set_title(f"{d['name']}: Return Distribution")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    fig.suptitle("Predicted vs Actual Return Distributions", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "4_return_distributions.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 5. Weekly PnL Waterfall (bar chart per model) ───────────────
    fig, axes = plt.subplots(n_models, 1, figsize=(12, 4 * n_models), squeeze=False)
    for i, key in enumerate(model_keys):
        d = plot_data[key]
        ax = axes[i, 0]
        wlog = d["weekly_log"]
        if not wlog:
            ax.set_visible(False)
            continue
        dates = [e["date"].strftime("%m/%d") for e in wlog]
        rets = [e["ret"] for e in wlog]
        bar_colors = [COLORS["nofee"] if r >= 0 else COLORS["fee"] for r in rets]
        ax.bar(dates, rets, color=bar_colors, edgecolor="white", linewidth=0.5)
        ax.axhline(0, color="k", linewidth=0.6)
        ax.set_ylabel("Weekly Return (%)")
        ax.set_title(f"{d['name']}: Weekly Returns (with fees)")
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Weekly PnL Waterfall", fontsize=13, y=1.01)
    fig.tight_layout()
    fig.savefig(out_dir / "5_weekly_pnl.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 6. Feature Importance (top 15, per model) ───────────────────
    fig, axes = plt.subplots(1, n_models, figsize=(6 * n_models, 6), squeeze=False)
    for i, key in enumerate(model_keys):
        d = plot_data[key]
        ax = axes[0, i]
        importances = d.get("feature_importances")
        if importances is None:
            ax.text(0.5, 0.5, "N/A", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(f"{d['name']}: Feature Importance")
            continue
        n_feat = min(15, len(importances))
        top_idx = np.argsort(importances)[-n_feat:]
        names = [FEATURE_NAMES[j] if j < len(FEATURE_NAMES) else f"feat_{j}" for j in top_idx]
        vals = importances[top_idx]
        ax.barh(range(n_feat), vals, color=COLORS.get(key, "#333"), edgecolor="white")
        ax.set_yticks(range(n_feat))
        ax.set_yticklabels(names, fontsize=8)
        ax.set_xlabel("Importance")
        ax.set_title(f"{d['name']}: Top {n_feat} Features")
        ax.grid(True, axis="x", alpha=0.3)
    fig.suptitle("Feature Importance (trained model)", fontsize=13, y=1.01)
    fig.tight_layout()
    fig.savefig(out_dir / "6_feature_importance.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 7. Residuals vs Predicted (heteroscedasticity check) ────────
    fig, axes = plt.subplots(1, n_models, figsize=(6 * n_models, 4.5), squeeze=False)
    for i, key in enumerate(model_keys):
        d = plot_data[key]
        ax = axes[0, i]
        pred = d["pred_all"]
        residuals = (y_test - pred) * 100
        ax.scatter(pred * 100, residuals, alpha=0.12, s=5,
                   color=COLORS.get(key, "#333"), rasterized=True)
        ax.axhline(0, color="k", linestyle="--", alpha=0.5)
        ax.set_xlabel("Predicted return (%)")
        ax.set_ylabel("Residual (actual - predicted) (%)")
        ax.set_title(f"{d['name']}: Residuals vs Predicted")
        ax.grid(True, alpha=0.3)
    fig.suptitle("Residuals vs Predicted (test set)", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "7_residuals_vs_predicted.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 8. Trade-level: Predicted vs Actual for EXECUTED trades ─────
    fig, axes = plt.subplots(1, n_models, figsize=(6 * n_models, 5), squeeze=False)
    for i, key in enumerate(model_keys):
        d = plot_data[key]
        ax = axes[0, i]
        trades = d.get("all_trades", [])
        if not trades:
            ax.text(0.5, 0.5, "No trades executed", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12)
            ax.set_title(f"{d['name']}: Executed Trades")
            continue
        tdf = pd.DataFrame(trades)
        profitable = tdf["ret_after_fees"] > 0
        ax.scatter(tdf.loc[profitable, "actual_ret"] * 100,
                   tdf.loc[profitable, "pred_ret"] * 100,
                   alpha=0.7, s=30, color=COLORS["nofee"], label="Profitable", zorder=3)
        ax.scatter(tdf.loc[~profitable, "actual_ret"] * 100,
                   tdf.loc[~profitable, "pred_ret"] * 100,
                   alpha=0.7, s=30, color=COLORS["fee"], label="Losing", zorder=3)
        lo = min(tdf["actual_ret"].min(), tdf["pred_ret"].min()) * 100
        hi = max(tdf["actual_ret"].max(), tdf["pred_ret"].max()) * 100
        ax.plot([lo, hi], [lo, hi], "k--", alpha=0.4, linewidth=1)
        ax.set_xlabel("Actual return (%)")
        ax.set_ylabel("Predicted return (%)")
        n_prof = profitable.sum()
        ax.set_title(f"{d['name']}: Executed Trades\n"
                     f"{len(tdf)} trades, {n_prof} profitable ({n_prof / len(tdf) * 100:.0f}%)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    fig.suptitle("Executed Trade Analysis: Predicted vs Actual", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "8_trade_scatter.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    logging.info("Saved 8 plots to %s", out_dir)
    return True


def run_backtest(
    game_id: str = "730",
    starting_balance: float = 100.0,
    fee_pct: float = 15.0,
    top_k: int = 5,
    model_keys: Optional[List[str]] = None,
    max_items: Optional[int] = None,
    min_predicted_return: float = 0.0,
    use_event_window: bool = True,
    test_months: int = 3,
    demo: bool = False,
    plot_dir: str = "backtest_output",
    no_plots: bool = False,
):
    if model_keys is None:
        model_keys = ["rf", "gb"]

    fee_rate = fee_pct / 100.0
    breakeven_return = (1.0 / (1.0 - fee_rate)) - 1.0

    # ── Header ──────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  STEAM MARKET BACKTEST" + ("  [DEMO MODE]" if demo else ""))
    print("=" * 80)
    print(f"  Game ID            : {game_id}")
    print(f"  Starting balance   : ${starting_balance:.2f}")
    print(f"  Sell fee           : {fee_pct:.1f}%  (break-even return: {breakeven_return * 100:.1f}%)")
    print(f"  Top-K picks / week : {top_k}")
    print(f"  Test window        : last {test_months} months of data")
    print(f"  Models             : {', '.join(MODELS[k][0] for k in model_keys)}")
    if demo:
        print(f"  Data source        : Synthetic (20 items, ~9 months)")
    print("=" * 80)

    # ── 1. Prepare data ────────────────────────────────────────────────
    if demo:
        logging.info("Generating synthetic demo data...")
        X, y, item_names, timestamps = _generate_demo_data()
    else:
        predictor = PricePredictor()

        from_date, to_date = None, None
        if use_event_window:
            try:
                with sqlite3.connect(predictor.db_path) as conn:
                    ev = pd.read_sql_query(
                        "SELECT MIN(start_date) AS s, MAX(end_date) AS e FROM cs2_events",
                        conn, parse_dates=["s", "e"],
                    )
                if not ev.empty and pd.notna(ev["s"].iloc[0]):
                    from_date = (ev["s"].iloc[0].normalize() - pd.Timedelta(days=14)).date().isoformat()
                    to_date = (ev["e"].iloc[0].normalize() + pd.Timedelta(days=30)).date().isoformat()
            except Exception:
                pass

        logging.info("Loading and preparing data (this may take a minute)...")
        result = predictor.prepare_data(
            game_id, max_items=max_items, from_date=from_date, to_date=to_date,
        )
        if result is None or not isinstance(result, tuple) or len(result) < 4:
            print("\nERROR: prepare_data returned an unexpected result.")
            print("       Run with --demo to see the backtest with synthetic data.\n")
            return
        X, y, item_names, timestamps = result
        if X is None or timestamps is None:
            print("\nERROR: No data available. Make sure you have price history in the database.")
            print("       Run with --demo to see the backtest with synthetic data.\n")
            return

    sort_idx = np.argsort(timestamps)
    X = X[sort_idx]
    y = y[sort_idx]
    item_names = [item_names[i] for i in sort_idx]
    timestamps = timestamps[sort_idx]

    # ── 1b. Sanitise NaN / Inf values from sparse DB data ────────────
    nan_mask = np.isnan(X).any(axis=1) | np.isinf(X).any(axis=1) | np.isnan(y) | np.isinf(y)
    n_bad = int(nan_mask.sum())
    if n_bad > 0:
        logging.warning("Dropped %d rows with NaN/Inf values (%.1f%% of data)", n_bad, n_bad / len(X) * 100)
        good = ~nan_mask
        X = X[good]
        y = y[good]
        item_names = [item_names[i] for i, g in enumerate(good) if g]
        timestamps = timestamps[good]

    if len(X) < 20:
        print("\nERROR: Not enough clean data for a meaningful backtest.")
        print("       Run with --demo to see the backtest with synthetic data.\n")
        return

    # ── 2. Chronological train / test split ─────────────────────────────
    all_dates = pd.Series(pd.to_datetime(timestamps).normalize())
    max_date = all_dates.max()
    test_start = max_date - pd.Timedelta(days=test_months * 30)

    train_mask = all_dates < test_start
    test_mask = all_dates >= test_start

    train_idx = train_mask.values
    test_idx = test_mask.values
    X_train, y_train = X[train_idx], y[train_idx]
    X_test, y_test = X[test_idx], y[test_idx]
    item_names_arr = np.array(item_names)
    test_item_names = item_names_arr[test_idx].tolist()
    test_timestamps = timestamps[test_idx]
    test_dates = all_dates[test_mask].reset_index(drop=True)

    print(f"\n  Observations  : {len(X):,} total")
    print(f"  Training set  : {len(X_train):,}  (before {test_start.strftime('%Y-%m-%d')})")
    print(f"  Test set (sim): {len(X_test):,}  ({test_start.strftime('%Y-%m-%d')}  to  {max_date.strftime('%Y-%m-%d')})")

    if len(X_train) < 100:
        print("\n  WARNING: Very small training set — results may be unreliable.\n")
    if len(X_test) < 10:
        print("\n  ERROR: Not enough test data for a meaningful backtest.\n")
        return

    # ── 3. Scale features ───────────────────────────────────────────────
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    test_prices = X_test[:, 0]   # feature index 0 = current price
    test_volumes = X_test[:, 4]  # feature index 4 = volume_ma7

    # Weekly buckets (non-overlapping 7-day periods)
    weeks = ((test_dates - test_start).dt.days // 7).values
    unique_weeks = sorted(set(weeks))

    # ── 4. Run simulation for each model ────────────────────────────────
    model_summaries = []
    plot_data: Dict[str, dict] = {}

    for model_key in model_keys:
        model_name, model_factory = MODELS[model_key]

        print(f"\n{'-' * 80}")
        print(f"  MODEL: {model_name}")
        print(f"{'-' * 80}")

        logging.info(f"Training {model_name}...")
        model = model_factory()
        model.fit(X_train_s, y_train)

        # Direction accuracy on full test set
        pred_all = model.predict(X_test_s)
        direction_hits = np.sum(np.sign(pred_all) == np.sign(y_test))
        direction_acc = direction_hits / len(y_test) * 100

        # ── Simulate week-by-week trading ───────────────────────────────
        balance = starting_balance
        balance_nf = starting_balance  # no-fee balance for comparison

        total_trades = 0
        wins = 0
        wins_nf = 0
        trade_returns = []
        trade_returns_nf = []
        all_trades = []
        weekly_log = []
        bal_curve = [starting_balance]
        bal_curve_nf = [starting_balance]

        for wk in unique_weeks:
            wk_mask = weeks == wk
            wk_idx = np.where(wk_mask)[0]
            if len(wk_idx) == 0:
                continue

            wk_pred = pred_all[wk_idx]
            wk_actual = y_test[wk_idx]
            wk_items = [test_item_names[i] for i in wk_idx]
            wk_prices = test_prices[wk_idx]
            wk_vols = test_volumes[wk_idx]
            wk_date = test_dates.iloc[wk_idx[0]]

            threshold = max(min_predicted_return, breakeven_return)
            MIN_TRADE_VOLUME = 3.0
            viable = np.where(
                (wk_pred > threshold) & (wk_vols >= MIN_TRADE_VOLUME)
            )[0]

            if len(viable) == 0:
                weekly_log.append(dict(
                    week=wk, date=wk_date, n=0,
                    bal=balance, bal_nf=balance_nf,
                    ret=0.0, ret_nf=0.0,
                ))
                bal_curve.append(balance)
                bal_curve_nf.append(balance_nf)
                continue

            pick_k = min(top_k, len(viable))
            best_in_viable = np.argsort(wk_pred[viable])[-pick_k:][::-1]
            picks = viable[best_in_viable]

            alloc = balance / pick_k
            alloc_nf = balance_nf / pick_k

            wk_pnl = 0.0
            wk_pnl_nf = 0.0

            for p in picks:
                pr = wk_pred[p]
                ar = wk_actual[p]
                ar_fee = (1 + ar) * (1 - fee_rate) - 1

                pnl = alloc * ar_fee
                pnl_nf = alloc_nf * ar

                wk_pnl += pnl
                wk_pnl_nf += pnl_nf
                total_trades += 1
                if ar_fee > 0:
                    wins += 1
                if ar > 0:
                    wins_nf += 1

                trade_returns.append(ar_fee)
                trade_returns_nf.append(ar)

                all_trades.append(dict(
                    week=wk, item=wk_items[p], buy_price=wk_prices[p],
                    pred_ret=pr, actual_ret=ar, ret_after_fees=ar_fee, pnl=pnl,
                ))

            balance += wk_pnl
            balance_nf += wk_pnl_nf

            wk_ret = wk_pnl / (balance - wk_pnl) * 100 if (balance - wk_pnl) > 0 else 0
            wk_ret_nf = wk_pnl_nf / (balance_nf - wk_pnl_nf) * 100 if (balance_nf - wk_pnl_nf) > 0 else 0

            weekly_log.append(dict(
                week=wk, date=wk_date, n=len(picks),
                bal=balance, bal_nf=balance_nf,
                ret=wk_ret, ret_nf=wk_ret_nf,
            ))
            bal_curve.append(balance)
            bal_curve_nf.append(balance_nf)

        # ── Weekly log table ────────────────────────────────────────────
        print(f"\n  {'Wk':>3} | {'Date':>12} | {'#':>3} | {'Balance':>11} | {'Wk Ret':>8} | {'No-Fee Bal':>11} | {'NF Ret':>8}")
        print(f"  {'-' * 72}")
        for e in weekly_log:
            print(
                f"  {e['week']:>3} | {e['date'].strftime('%Y-%m-%d'):>12} | "
                f"{e['n']:>3} | ${e['bal']:>9.2f} | {e['ret']:>+7.2f}% | "
                f"${e['bal_nf']:>9.2f} | {e['ret_nf']:>+7.2f}%"
            )

        # ── Equity curve sparkline ──────────────────────────────────────
        print(f"\n  Equity curve (with fees):  {_sparkline(bal_curve, 50)}")
        print(f"  Equity curve (no fees) :  {_sparkline(bal_curve_nf, 50)}")

        # ── Summary statistics ──────────────────────────────────────────
        total_ret = (balance - starting_balance) / starting_balance * 100
        total_ret_nf = (balance_nf - starting_balance) / starting_balance * 100
        max_dd = _max_drawdown(bal_curve)
        max_dd_nf = _max_drawdown(bal_curve_nf)
        win_rate = wins / total_trades * 100 if total_trades else 0
        win_rate_nf = wins_nf / total_trades * 100 if total_trades else 0
        avg_ret = np.mean(trade_returns) * 100 if trade_returns else 0
        avg_ret_nf = np.mean(trade_returns_nf) * 100 if trade_returns_nf else 0
        std_ret = np.std(trade_returns) * 100 if len(trade_returns) > 1 else 0
        sharpe = (np.mean(trade_returns) / np.std(trade_returns)) if len(trade_returns) > 1 and np.std(trade_returns) > 0 else 0

        gross_profits = sum(r for r in trade_returns if r > 0)
        gross_losses = abs(sum(r for r in trade_returns if r < 0))
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else float("inf")
        profit_factor_nf = (
            sum(r for r in trade_returns_nf if r > 0) / abs(sum(r for r in trade_returns_nf if r < 0))
            if any(r < 0 for r in trade_returns_nf) else float("inf")
        )

        downside = [r for r in trade_returns if r < 0]
        downside_std = np.std(downside) if len(downside) > 1 else 0
        sortino = (np.mean(trade_returns) / downside_std) if downside_std > 0 else 0

        print(f"\n  +{'-' * 33}+{'-' * 16}+{'-' * 16}+")
        print(f"  | {'Metric':31s} | {'With Fees':>14s} | {'No Fees':>14s} |")
        print(f"  +{'-' * 33}+{'-' * 16}+{'-' * 16}+")
        print(f"  | {'Starting Balance':31s} | ${starting_balance:>12.2f} | ${starting_balance:>12.2f} |")
        print(f"  | {'Final Balance':31s} | ${balance:>12.2f} | ${balance_nf:>12.2f} |")
        print(f"  | {'Total Return':31s} | {total_ret:>+12.2f}% | {total_ret_nf:>+12.2f}% |")
        print(f"  | {'Max Drawdown':31s} | {max_dd:>12.2f}% | {max_dd_nf:>12.2f}% |")
        print(f"  | {'Total Trades':31s} | {total_trades:>14,} | {total_trades:>14,} |")
        print(f"  | {'Win Rate':31s} | {win_rate:>12.1f}% | {win_rate_nf:>12.1f}% |")
        print(f"  | {'Avg Return / Trade':31s} | {avg_ret:>+12.2f}% | {avg_ret_nf:>+12.2f}% |")
        pf_str = f"{profit_factor:>14.2f}" if profit_factor != float("inf") else "             ∞"
        pf_nf_str = f"{profit_factor_nf:>14.2f}" if profit_factor_nf != float("inf") else "             ∞"
        print(f"  | {'Profit Factor':31s} | {pf_str} | {pf_nf_str} |")
        print(f"  | {'Sharpe (per-trade)':31s} | {sharpe:>14.3f} |                |")
        print(f"  | {'Sortino (per-trade)':31s} | {sortino:>14.3f} |                |")
        print(f"  | {'Direction Accuracy (full test)':31s} | {direction_acc:>12.1f}% |                |")
        print(f"  +{'-' * 33}+{'-' * 16}+{'-' * 16}+")

        # Best / worst trades
        if all_trades:
            tdf = pd.DataFrame(all_trades).sort_values("pnl", ascending=False)

            print(f"\n  Top 5 Best Trades:")
            for _, t in tdf.head(5).iterrows():
                print(
                    f"    {t['item'][:42]:42s} | "
                    f"${t['buy_price']:>7.2f} | "
                    f"Pred {t['pred_ret'] * 100:>+6.1f}% | "
                    f"Actual {t['actual_ret'] * 100:>+6.1f}% | "
                    f"PnL ${t['pnl']:>+8.2f}"
                )

            print(f"\n  Top 5 Worst Trades:")
            for _, t in tdf.tail(5).iterrows():
                print(
                    f"    {t['item'][:42]:42s} | "
                    f"${t['buy_price']:>7.2f} | "
                    f"Pred {t['pred_ret'] * 100:>+6.1f}% | "
                    f"Actual {t['actual_ret'] * 100:>+6.1f}% | "
                    f"PnL ${t['pnl']:>+8.2f}"
                )

        model_summaries.append(dict(
            model=model_name, key=model_key,
            final=balance, final_nf=balance_nf,
            ret=total_ret, ret_nf=total_ret_nf,
            dd=max_dd, dd_nf=max_dd_nf,
            trades=total_trades, win_rate=win_rate, win_rate_nf=win_rate_nf,
            sharpe=sharpe, sortino=sortino,
            profit_factor=profit_factor,
            direction_acc=direction_acc,
        ))

        try:
            feat_imp = model.feature_importances_
        except Exception:
            feat_imp = None

        plot_data[model_key] = dict(
            name=model_name,
            pred_all=pred_all,
            bal_curve=bal_curve,
            bal_curve_nf=bal_curve_nf,
            weekly_log=weekly_log,
            all_trades=all_trades,
            feature_importances=feat_imp,
        )

    # ── Side-by-side comparison (if both models ran) ────────────────────
    if len(model_summaries) > 1:
        print(f"\n{'=' * 80}")
        print(f"  HEAD-TO-HEAD COMPARISON")
        print(f"{'=' * 80}")
        print(f"\n  {'Metric':<28s}", end="")
        for s in model_summaries:
            print(f" | {s['model']:>18s}", end="")
        print()
        print(f"  {'-' * 28}", end="")
        for _ in model_summaries:
            print(f"-+{'-' * 19}", end="")
        print()

        rows = [
            ("Final Balance", lambda s: f"${s['final']:>15.2f}"),
            ("Total Return", lambda s: f"{s['ret']:>+15.2f}%"),
            ("Final Balance (no fees)", lambda s: f"${s['final_nf']:>15.2f}"),
            ("Return (no fees)", lambda s: f"{s['ret_nf']:>+15.2f}%"),
            ("Max Drawdown", lambda s: f"{s['dd']:>15.2f}%"),
            ("Win Rate (w/ fees)", lambda s: f"{s['win_rate']:>15.1f}%"),
            ("Win Rate (no fees)", lambda s: f"{s['win_rate_nf']:>15.1f}%"),
            ("Profit Factor", lambda s: f"{s['profit_factor']:>18.2f}" if s['profit_factor'] != float("inf") else "                 ∞"),
            ("Sharpe (per-trade)", lambda s: f"{s['sharpe']:>18.3f}"),
            ("Sortino (per-trade)", lambda s: f"{s['sortino']:>18.3f}"),
            ("Direction Accuracy", lambda s: f"{s['direction_acc']:>15.1f}%"),
            ("Total Trades", lambda s: f"{s['trades']:>18,}"),
        ]
        for label, fmt in rows:
            print(f"  {label:<28s}", end="")
            for s in model_summaries:
                print(f" | {fmt(s)}", end="")
            print()

    # ── Benchmark ───────────────────────────────────────────────────────
    avg_mkt = np.mean(y_test) * 100
    med_mkt = np.median(y_test) * 100
    pct_positive = np.mean(y_test > 0) * 100
    print(f"\n{'=' * 80}")
    print(f"  MARKET BENCHMARK  (test period, {len(y_test):,} observations)")
    print(f"    Mean 7-day return   : {avg_mkt:>+.2f}%")
    print(f"    Median 7-day return : {med_mkt:>+.2f}%")
    print(f"    % items with gain   : {pct_positive:.1f}%")
    print(f"{'=' * 80}\n")

    # ── Plots ─────────────────────────────────────────────────────────
    if not no_plots:
        out = Path(plot_dir)
        did_plot = _generate_plots(
            plot_data=plot_data,
            y_test=y_test,
            test_dates=test_dates,
            test_start=test_start,
            starting_balance=starting_balance,
            fee_pct=fee_pct,
            out_dir=out,
        )
        if did_plot:
            print(f"  Plots saved to: {out.resolve()}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Backtest a trading bot on Steam market data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.backtest
  python -m scripts.backtest --model rf --top-k 3
  python -m scripts.backtest --fee-pct 0 --top-k 10
  python -m scripts.backtest --starting-balance 500 --max-items 200
""",
    )
    parser.add_argument("--game-id", type=str, default="730")
    parser.add_argument("--starting-balance", type=float, default=100.0,
                        help="Starting cash in dollars (default: 100)")
    parser.add_argument("--fee-pct", type=float, default=15.0,
                        help="Steam sell fee %% (default: 15 = 5%% Steam + 10%% CS2)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Max items to buy each week (default: 5)")
    parser.add_argument("--model", type=str, default="all",
                        choices=["rf", "gb", "all"],
                        help="Which model(s) to backtest (default: all)")
    parser.add_argument("--max-items", type=int, default=None,
                        help="Limit DB items for faster runs (default: all)")
    parser.add_argument("--min-predicted-return", type=float, default=0.0,
                        help="Extra minimum predicted return threshold (default: 0)")
    parser.add_argument("--no-event-window", action="store_true",
                        help="Disable CS2 event-window filtering")
    parser.add_argument("--test-months", type=int, default=3,
                        help="Months of data to use as test window (default: 3)")
    parser.add_argument("--demo", action="store_true",
                        help="Run with synthetic data (no database needed)")
    parser.add_argument("--plot-dir", type=str, default="backtest_output",
                        help="Directory for plot images (default: backtest_output)")
    parser.add_argument("--no-plots", action="store_true",
                        help="Skip plot generation")
    args = parser.parse_args()

    model_keys = ["rf", "gb"] if args.model == "all" else [args.model]

    run_backtest(
        game_id=args.game_id,
        starting_balance=args.starting_balance,
        fee_pct=args.fee_pct,
        top_k=args.top_k,
        model_keys=model_keys,
        max_items=args.max_items,
        min_predicted_return=args.min_predicted_return,
        use_event_window=not args.no_event_window,
        test_months=args.test_months,
        demo=args.demo,
        plot_dir=args.plot_dir,
        no_plots=args.no_plots,
    )


if __name__ == "__main__":
    main()
