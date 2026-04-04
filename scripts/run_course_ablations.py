#!/usr/bin/env python
"""Run a small grid of short LSTM trainings for course experiments.

Each experiment trains with few epochs (default 3) and records validation metrics
stored in ``best_model.pt`` (``metrics`` field).

Hypotheses (document in your report)::

    pooled_vs_holdout — Does item holdout lower val accuracy but better reflect
        generalization to unseen skins?
    seq_len — Does a longer history (30 vs 14) help within the same budget?

Usage::

    python scripts/run_course_ablations.py --dry-run          # print plan only
    python scripts/run_course_ablations.py --max-items 25 --epochs 3

Results append to ``course_outputs/ablation_results.csv``.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPERIMENTS = [
    {
        "id": "pooled_baseline",
        "hypothesis": "Pooled chronological split (legacy) often shows higher val acc.",
        "args": ["--split-mode", "pooled"],
    },
    {
        "id": "item_holdout",
        "hypothesis": "Holding out whole items reduces optimistic accuracy.",
        "args": ["--split-mode", "item_holdout", "--holdout-fraction", "0.2", "--holdout-seed", "42"],
    },
    {
        "id": "seq_len_14",
        "hypothesis": "Shorter context may underfit regime shifts.",
        "args": ["--split-mode", "pooled", "--seq-len", "14"],
    },
]


def read_checkpoint_metrics(ckpt_path: Path) -> dict:
    import torch

    st = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    return dict(st.get("metrics", {}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Course LSTM ablation runner")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only")
    parser.add_argument("--max-items", type=int, default=25)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--loss", default="ce", choices=["ce", "weighted-ce", "focal"])
    parser.add_argument("--out-dir", type=str, default="course_outputs")
    args = parser.parse_args()

    out_root = PROJECT_ROOT / args.out_dir
    out_root.mkdir(parents=True, exist_ok=True)
    csv_path = out_root / "ablation_results.csv"

    rows = []
    for ex in EXPERIMENTS:
        save_dir = out_root / ex["id"]
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "train_lstm.py"),
            "--max-items",
            str(args.max_items),
            "--epochs",
            str(args.epochs),
            "--loss",
            args.loss,
            "--save-dir",
            str(save_dir),
            "--patience",
            "99",
        ] + ex["args"]

        print("\n#", ex["id"])
        print("  ", ex["hypothesis"])
        print("  ", " ".join(cmd))

        if args.dry_run:
            continue

        r = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if r.returncode != 0:
            print(f"  !! failed exit={r.returncode}")
            rows.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "id": ex["id"],
                    "hypothesis": ex["hypothesis"],
                    "exit_code": r.returncode,
                    "val_loss": "",
                    "val_accuracy": "",
                    "val_f1_macro": "",
                }
            )
            continue

        ckpt = save_dir / "best_model.pt"
        metrics = read_checkpoint_metrics(ckpt) if ckpt.is_file() else {}
        rows.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "id": ex["id"],
                "hypothesis": ex["hypothesis"],
                "exit_code": 0,
                "val_loss": metrics.get("val_loss", ""),
                "val_accuracy": metrics.get("val_accuracy", ""),
                "val_f1_macro": metrics.get("val_f1_macro", ""),
            }
        )

    if args.dry_run:
        print("\nDry run only. Re-run without --dry-run to execute.\n")
        return

    write_header = not csv_path.is_file()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "id",
                "hypothesis",
                "exit_code",
                "val_loss",
                "val_accuracy",
                "val_f1_macro",
            ],
        )
        if write_header:
            w.writeheader()
        for row in rows:
            w.writerow(row)

    print(f"\nAppended results to {csv_path}\n")


if __name__ == "__main__":
    main()
