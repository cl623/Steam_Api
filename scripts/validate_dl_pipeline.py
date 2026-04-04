#!/usr/bin/env python
"""Smoke-test for the V3.0 deep-learning data pipeline.

Loads data from the SQLite database, builds sliding-window sequences,
normalizes them, wraps in DataLoaders, and prints shape/statistics
for every step so you can verify correctness before training.

Usage::

    python scripts/validate_dl_pipeline.py
    python scripts/validate_dl_pipeline.py --max-items 50 --seq-len 30
    python scripts/validate_dl_pipeline.py --use-event-window
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so ``ml`` is importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V3.0 DL data pipeline")
    parser.add_argument("--game-id", default="730")
    parser.add_argument("--max-items", type=int, default=50)
    parser.add_argument("--seq-len", type=int, default=30)
    parser.add_argument("--prediction-days", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--use-event-window", action="store_true")
    parser.add_argument("--norm-method", choices=["minmax", "standard"], default="minmax")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )
    log = logging.getLogger("validate_dl")

    db_path = PROJECT_ROOT / "data" / "market_data.db"
    if not db_path.exists():
        log.error("Database not found at %s", db_path)
        sys.exit(1)

    # ── Step 1: raw sequence loading ────────────────────────────────────────
    log.info("=" * 60)
    log.info("STEP 1 – Loading raw sequences from database")
    log.info("=" * 60)

    from ml.deep_learning.dataset import (
        load_sequences_from_db,
        NUM_TEMPORAL_FEATURES,
        NUM_STATIC_FEATURES,
        TEMPORAL_FEATURE_COLS,
        STATIC_FEATURE_KEYS,
    )

    seqs, statics, targets, names, timestamps = load_sequences_from_db(
        db_path,
        game_id=args.game_id,
        seq_len=args.seq_len,
        prediction_days=args.prediction_days,
        max_items=args.max_items,
        use_event_window=args.use_event_window,
    )

    if len(targets) == 0:
        log.error("No samples produced.  Check your database or lower --max-items.")
        sys.exit(1)

    log.info("Samples loaded: %d", len(targets))
    log.info("Sequence shape : (%d, %d)  – (seq_len, temporal_features)", args.seq_len, NUM_TEMPORAL_FEATURES)
    log.info("Static shape   : (%d,)     – (static_features,)", NUM_STATIC_FEATURES)
    log.info("Temporal cols  : %s", TEMPORAL_FEATURE_COLS)
    log.info("Static keys    : %s", STATIC_FEATURE_KEYS)

    # Quick sanity on a single sample
    s0 = seqs[0]
    log.info("Sample 0  sequence dtype=%s  min=%.4f  max=%.4f  has_nan=%s",
             s0.dtype, np.nanmin(s0), np.nanmax(s0), np.isnan(s0).any())
    log.info("Sample 0  static=%s", statics[0])
    log.info("Sample 0  target (log-return)=%.6f  item=%s  ts=%s",
             targets[0], names[0], timestamps[0])

    # ── Step 2: normalization ───────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("STEP 2 – Fitting normalizer (method=%s)", args.norm_method)
    log.info("=" * 60)

    from ml.deep_learning.normalization import SequenceNormalizer

    split = int(len(seqs) * 0.8)
    train_seqs = seqs[:split]
    test_seqs = seqs[split:]

    norm = SequenceNormalizer(method=args.norm_method)
    norm.fit(train_seqs)
    train_scaled = norm.transform(train_seqs)
    test_scaled = norm.transform(test_seqs)

    all_train = np.concatenate(train_scaled, axis=0)
    all_test = np.concatenate(test_scaled, axis=0)

    log.info("Train scaled  shape=%s  min=%.4f  max=%.4f  mean=%.4f  std=%.4f",
             all_train.shape, all_train.min(), all_train.max(),
             all_train.mean(), all_train.std())
    log.info("Test  scaled  shape=%s  min=%.4f  max=%.4f  mean=%.4f  std=%.4f",
             all_test.shape, all_test.min(), all_test.max(),
             all_test.mean(), all_test.std())

    # Per-feature stats in train
    log.info("")
    log.info("Per-feature stats (train, after scaling):")
    for i, col in enumerate(TEMPORAL_FEATURE_COLS):
        vals = all_train[:, i]
        log.info("  %-28s  min=%8.4f  max=%8.4f  mean=%8.4f  std=%8.4f",
                 col, vals.min(), vals.max(), vals.mean(), vals.std())

    # ── Step 3: DataLoader ──────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("STEP 3 – Building DataLoaders (batch_size=%d)", args.batch_size)
    log.info("=" * 60)

    from ml.deep_learning.dataset import build_dataloaders

    train_loader, test_loader, norm2, split_meta = build_dataloaders(
        db_path,
        game_id=args.game_id,
        seq_len=args.seq_len,
        prediction_days=args.prediction_days,
        batch_size=args.batch_size,
        max_items=args.max_items,
        use_event_window=args.use_event_window,
    )

    log.info("Split meta: %s", split_meta)
    log.info("Train batches: %d", len(train_loader))
    log.info("Test  batches: %d", len(test_loader))

    batch = next(iter(train_loader))
    log.info("First batch keys: %s", list(batch.keys()))
    log.info("  sequence shape : %s", tuple(batch["sequence"].shape))
    log.info("  static   shape : %s", tuple(batch["static"].shape))
    log.info("  target   shape : %s", tuple(batch["target"].shape))
    log.info("  item_names[:3] : %s", batch["item_name"][:3])

    # Confirm the 3-D tensor shape matches expectations
    B, S, F = batch["sequence"].shape
    assert S == args.seq_len, f"seq_len mismatch: {S} != {args.seq_len}"
    assert F == NUM_TEMPORAL_FEATURES, f"feature dim mismatch: {F} != {NUM_TEMPORAL_FEATURES}"
    log.info("  ✓ Tensor shape validated: (batch=%d, seq_len=%d, features=%d)", B, S, F)

    # Target distribution
    all_tgt = np.array(targets)
    log.info("")
    log.info("Target (log-return) distribution:")
    log.info("  count=%d  mean=%.4f  std=%.4f  min=%.4f  max=%.4f",
             len(all_tgt), all_tgt.mean(), all_tgt.std(), all_tgt.min(), all_tgt.max())
    pcts = np.percentile(all_tgt, [5, 25, 50, 75, 95])
    log.info("  percentiles [5,25,50,75,95]: %s", [f"{p:.4f}" for p in pcts])

    log.info("")
    log.info("=" * 60)
    log.info("Pipeline validation PASSED")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
