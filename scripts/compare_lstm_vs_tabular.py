#!/usr/bin/env python
"""Compare tabular RF/GB vs LSTM on the **same item-level holdout split**.

Tabular models use ``PricePredictor.prepare_data`` (7-day return targets, clipped).
LSTM uses sliding windows and log-return bucket labels.  This script:

1. Builds LSTM DataLoaders with ``split_mode=item_holdout`` (same seed as training).
2. Trains RF and GB on tabular rows whose ``market_hash_name`` is in ``train_items``.
3. Evaluates all models on **test items only** with aligned **bucket** metrics
   (``macro-F1``, accuracy) using ``BUCKET_EDGES``.
4. Reports **MAE in log-return space** (same transform as the LSTM target).

Rows from tabular and LSTM are **not** aligned sample-by-sample (different feature
construction and row density); comparison is on the **same held-out item names**.

Usage::

    python scripts/compare_lstm_vs_tabular.py --max-items 50 --holdout-seed 42
    python scripts/compare_lstm_vs_tabular.py --max-items 50 \\
        --lstm-checkpoint models_lstm/best_model.pt
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ml.deep_learning.buckets import (
    clipped_returns_to_log_returns,
    expected_log_return_from_probs,
    log_returns_to_labels,
    returns_to_bucket_labels,
)
from ml.deep_learning.dataset import build_dataloaders
from ml.deep_learning.model import load_checkpoint
from ml.deep_learning.normalization import SequenceNormalizer
from ml.price_predictor import PricePredictor

logger = logging.getLogger("compare_lstm_vs_tabular")


def collect_lstm_logits(model, loader, device):
    import torch

    model.eval()
    all_logits = []
    all_targets = []
    with torch.no_grad():
        for batch in loader:
            seq = batch["sequence"].to(device)
            static = batch["static"].to(device)
            logits = model(seq, static)
            all_logits.append(logits.cpu().numpy())
            all_targets.append(batch["target"].numpy())
    return np.concatenate(all_logits), np.concatenate(all_targets)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare LSTM vs RF/GB with item holdout")
    parser.add_argument("--game-id", default="730")
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--seq-len", type=int, default=30)
    parser.add_argument("--prediction-days", type=int, default=7)
    parser.add_argument("--use-event-window", action="store_true")
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--holdout-seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument(
        "--lstm-checkpoint",
        type=str,
        default=None,
        help="Path to best_model.pt; if omitted, only tabular models are evaluated",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    db_path = PROJECT_ROOT / "data" / "market_data.db"
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    _, _, _, meta = build_dataloaders(
        db_path,
        game_id=args.game_id,
        seq_len=args.seq_len,
        prediction_days=args.prediction_days,
        batch_size=args.batch_size,
        max_items=args.max_items,
        use_event_window=args.use_event_window,
        split_mode="item_holdout",
        holdout_fraction=args.holdout_fraction,
        holdout_seed=args.holdout_seed,
    )

    train_items = set(meta["train_items"])
    test_items = set(meta["test_items"])
    logger.info("Train items: %d  Test items: %d", len(train_items), len(test_items))

    from_date = None
    to_date = None
    if args.use_event_window:
        import sqlite3
        import pandas as pd

        with sqlite3.connect(db_path) as conn:
            try:
                ev = pd.read_sql_query(
                    "SELECT MIN(start_date) AS s, MAX(end_date) AS e FROM cs2_events",
                    conn,
                    parse_dates=["s", "e"],
                )
                if not ev.empty and pd.notna(ev["s"].iloc[0]):
                    from_date = (
                        ev["s"].iloc[0].normalize() - pd.Timedelta(days=14)
                    ).date().isoformat()
                    to_date = (
                        ev["e"].iloc[0].normalize() + pd.Timedelta(days=30)
                    ).date().isoformat()
            except Exception as exc:
                logging.warning("Event window not applied to tabular data: %s", exc)

    predictor = PricePredictor(db_path=str(db_path))
    out = predictor.prepare_data(
        args.game_id,
        max_items=args.max_items,
        prediction_days=args.prediction_days,
        from_date=from_date,
        to_date=to_date,
    )
    if out[0] is None:
        logger.error("prepare_data returned no rows")
        sys.exit(1)
    X, y_ret, item_names, _ts = out
    item_names = np.asarray(item_names)

    tr_mask = np.array([n in train_items for n in item_names], dtype=bool)
    te_mask = np.array([n in test_items for n in item_names], dtype=bool)

    if tr_mask.sum() == 0 or te_mask.sum() == 0:
        logger.error(
            "Empty train or test tabular split (train=%d test=%d). "
            "Check max_items / item overlap with LSTM bundles.",
            tr_mask.sum(),
            te_mask.sum(),
        )
        sys.exit(1)

    X_tr, y_tr = X[tr_mask], y_ret[tr_mask]
    X_te, y_te = X[te_mask], y_ret[te_mask]

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)

    y_te_lr = clipped_returns_to_log_returns(y_te.astype(np.float64))
    true_labels = log_returns_to_labels(y_te_lr)

    logger.info("Tabular test rows (held-out items only): %d", len(y_te))

    print("\n=== Tabular models (test items, bucket metrics) ===\n")

    for name, model in [
        ("rf", RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)),
        ("gb", HistGradientBoostingRegressor(
            max_depth=6, learning_rate=0.05, max_iter=300, random_state=42,
        )),
    ]:
        model.fit(X_tr_s, y_tr)
        pred_ret = model.predict(X_te_s)
        pred_labels = returns_to_bucket_labels(pred_ret.astype(np.float64))
        acc = accuracy_score(true_labels, pred_labels)
        f1m = f1_score(true_labels, pred_labels, average="macro", zero_division=0)
        pred_lr = clipped_returns_to_log_returns(pred_ret.astype(np.float64))
        mae_lr = mean_absolute_error(y_te_lr, pred_lr)
        print(f"  {name.upper():4}  bucket_acc={acc:.4f}  macro_f1={f1m:.4f}  MAE_logret={mae_lr:.4f}")

    if args.lstm_checkpoint:
        import torch
        import torch.nn.functional as F

        ckpt_path = Path(args.lstm_checkpoint)
        if not ckpt_path.is_file():
            logger.error("Checkpoint not found: %s", ckpt_path)
            sys.exit(1)

        norm_path = ckpt_path.parent / "normalizer.npz"
        if not norm_path.is_file():
            logger.error(
                "Missing %s — LSTM evaluation requires the normalizer saved with training.",
                norm_path,
            )
            sys.exit(1)
        loaded_norm = SequenceNormalizer.load(norm_path)

        train_loader, test_loader, _, _meta2 = build_dataloaders(
            db_path,
            game_id=args.game_id,
            seq_len=args.seq_len,
            prediction_days=args.prediction_days,
            batch_size=args.batch_size,
            max_items=args.max_items,
            use_event_window=args.use_event_window,
            split_mode="item_holdout",
            holdout_fraction=args.holdout_fraction,
            holdout_seed=args.holdout_seed,
            normalizer=loaded_norm,
        )
        assert _meta2["test_items"] == meta["test_items"]

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, _ = load_checkpoint(ckpt_path, device=device)

        logits, y_lstm = collect_lstm_logits(model, test_loader, device)
        probs = F.softmax(torch.from_numpy(logits), dim=-1).numpy()
        pred_labels = logits.argmax(axis=-1)
        lstm_true_labels = log_returns_to_labels(y_lstm)

        acc = accuracy_score(lstm_true_labels, pred_labels)
        f1m = f1_score(lstm_true_labels, pred_labels, average="macro", zero_division=0)
        exp_lr = expected_log_return_from_probs(probs)
        mae_lr = mean_absolute_error(
            np.asarray(y_lstm, dtype=np.float32), exp_lr.astype(np.float32)
        )

        print("\n=== LSTM (same item holdout, test windows) ===\n")
        print(f"  LSTM  bucket_acc={acc:.4f}  macro_f1={f1m:.4f}  MAE_logret={mae_lr:.4f}")
        print(f"        test windows: {len(y_lstm)}")
    else:
        print("\n(Skipping LSTM: pass --lstm-checkpoint to include)\n")

    print(
        "\nNote: Tabular row count and LSTM window count differ; "
        "bucket metrics are on each model's own test tensors for the same item names.\n"
    )


if __name__ == "__main__":
    main()
