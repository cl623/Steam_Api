#!/usr/bin/env python
"""Decile lift chart: rank LSTM test predictions vs realized log-return targets.

Scores each window by **P(Massive Spike)** (last bucket) by default, or by
**expected log-return** from softmax × bucket midpoints (``--score expected``).

Requires ``best_model.pt`` and ``normalizer.npz`` from the same training run.
Rebuilds the test set using the same ``split_mode`` / holdout / ``max_items`` as training
(document these in ``split_meta.json`` next to the checkpoint).

Usage::

    python scripts/eval_lift_lstm.py --lstm-dir models_lstm --max-items 50
    python scripts/eval_lift_lstm.py --checkpoint models_lstm/best_model.pt \\
        --normalizer models_lstm/normalizer.npz --split-mode item_holdout
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="LSTM decile lift (test set)")
    parser.add_argument(
        "--lstm-dir",
        type=str,
        default=None,
        help="Directory containing best_model.pt and normalizer.npz",
    )
    parser.add_argument("--checkpoint", type=str, default=None)
    parser.add_argument("--normalizer", type=str, default=None)
    parser.add_argument("--game-id", default="730")
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--seq-len", type=int, default=30)
    parser.add_argument("--prediction-days", type=int, default=7)
    parser.add_argument("--use-event-window", action="store_true")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument(
        "--split-mode",
        choices=["pooled", "item_holdout"],
        default="pooled",
    )
    parser.add_argument("--holdout-fraction", type=float, default=0.2)
    parser.add_argument("--holdout-seed", type=int, default=42)
    parser.add_argument(
        "--score",
        choices=["spike", "expected"],
        default="spike",
        help="spike=P(bucket 3); expected=E[log-return] from probabilities",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="course_eval/lift_deciles.png",
        help="Output plot path (also prints table to stdout)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    log = logging.getLogger("eval_lift")

    if args.lstm_dir:
        d = Path(args.lstm_dir)
        ckpt_path = d / "best_model.pt"
        norm_path = d / "normalizer.npz"
    else:
        ckpt_path = Path(args.checkpoint) if args.checkpoint else None
        norm_path = Path(args.normalizer) if args.normalizer else None

    if ckpt_path is None or not ckpt_path.is_file():
        log.error("Need --lstm-dir or --checkpoint pointing to best_model.pt")
        sys.exit(1)
    if norm_path is None or not norm_path.is_file():
        log.error("Need normalizer.npz (via --lstm-dir or --normalizer)")
        sys.exit(1)

    import torch
    import torch.nn.functional as F

    from ml.deep_learning.buckets import NUM_BUCKETS, expected_log_return_from_probs
    from ml.deep_learning.dataset import build_dataloaders
    from ml.deep_learning.model import load_checkpoint
    from ml.deep_learning.normalization import SequenceNormalizer

    db_path = PROJECT_ROOT / "data" / "market_data.db"
    if not db_path.exists():
        log.error("Database not found: %s", db_path)
        sys.exit(1)

    meta_json = ckpt_path.parent / "split_meta.json"
    if meta_json.is_file():
        import json

        with open(meta_json, encoding="utf-8") as f:
            saved = json.load(f)
        log.info("Loaded %s (split_mode=%s)", meta_json, saved.get("split_mode"))
        args.split_mode = saved.get("split_mode", args.split_mode)
        args.holdout_fraction = saved.get("holdout_fraction", args.holdout_fraction)
        args.holdout_seed = saved.get("holdout_seed", args.holdout_seed)
        if saved.get("max_items") is not None:
            args.max_items = saved.get("max_items")
        args.seq_len = saved.get("seq_len", args.seq_len)
        args.prediction_days = saved.get("prediction_days", args.prediction_days)
        args.use_event_window = bool(saved.get("use_event_window", args.use_event_window))

    normalizer = SequenceNormalizer.load(norm_path)
    _, test_loader, _, _split_meta = build_dataloaders(
        db_path,
        game_id=args.game_id,
        seq_len=args.seq_len,
        prediction_days=args.prediction_days,
        batch_size=args.batch_size,
        max_items=args.max_items,
        use_event_window=args.use_event_window,
        split_mode=args.split_mode,
        holdout_fraction=args.holdout_fraction,
        holdout_seed=args.holdout_seed,
        normalizer=normalizer,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, _ = load_checkpoint(ckpt_path, device=device)
    model.eval()

    all_scores = []
    all_y = []
    with torch.no_grad():
        for batch in test_loader:
            seq = batch["sequence"].to(device)
            static = batch["static"].to(device)
            logits = model(seq, static)
            probs = F.softmax(logits, dim=-1).cpu().numpy()
            if args.score == "spike":
                s = probs[:, NUM_BUCKETS - 1]
            else:
                s = expected_log_return_from_probs(probs)
            all_scores.append(np.asarray(s, dtype=np.float64))
            all_y.append(batch["target"].numpy())

    scores = np.concatenate(all_scores)
    y = np.concatenate(all_y)
    n = len(scores)
    order = np.argsort(scores)
    n_dec = 10
    print("\n=== Decile lift (1=lowest score, 10=highest) ===\n")
    print(f"score={args.score}  test_windows={n}  split={args.split_mode}\n")
    means = []
    for d in range(n_dec):
        lo = int(d * n / n_dec)
        hi = int((d + 1) * n / n_dec)
        idx = order[lo:hi]
        m = float(y[idx].mean()) if len(idx) else float("nan")
        means.append(m)
        print(f"  decile {d+1:2d}  n={len(idx):6d}  mean_log_return={m:+.4f}")

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(range(1, n_dec + 1), means, color="steelblue", edgecolor="black")
        ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_xlabel("Decile (low → high model score)")
        ax.set_ylabel("Mean realized log-return")
        ax.set_title(f"LSTM lift ({args.score}) — {args.split_mode}")
        fig.tight_layout()
        fig.savefig(out_path, dpi=150)
        plt.close()
        log.info("Saved plot -> %s", out_path)
    except ImportError:
        log.warning("matplotlib not installed; skipped plot")


if __name__ == "__main__":
    main()
