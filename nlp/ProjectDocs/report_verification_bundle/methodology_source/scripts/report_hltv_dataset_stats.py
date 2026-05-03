#!/usr/bin/env python
"""
Reproducible dataset summary for HLTV sentiment SQLite DB (comments + matches).

Writes JSON to --out-json and optional exploration figures to --figures-dir.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from nlp.dataset import (  # noqa: E402
    add_weak_labels,
    default_db_path,
    load_comments_dataframe,
)
from nlp.time_windows import add_comment_phase  # noqa: E402

logger = logging.getLogger("report_hltv_stats")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out-json",
        type=Path,
        default=PROJECT_ROOT / "nlp" / "ProjectDocs" / "dataset_stats.json",
    )
    ap.add_argument(
        "--figures-dir",
        type=Path,
        default=PROJECT_ROOT / "nlp" / "ProjectDocs" / "figures",
    )
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        logger.error("DB not found: %s", db_path)
        return 1

    raw = load_comments_dataframe(db_path, limit=args.limit)
    if raw.empty:
        logger.error("No comments.")
        return 1

    df = add_weak_labels(raw)
    df = add_comment_phase(df)

    names = {0: "neg", 1: "neu", 2: "pos"}
    weak_counts = df["weak_label"].value_counts().reindex([0, 1, 2], fill_value=0)
    gold_n = int(df["gold_label"].notna().sum()) if "gold_label" in df.columns else 0

    ts = df["posted_at_unix"]
    ts_valid = ts.notna() & np.isfinite(ts.astype(float))
    ctx = df["score_context"].astype(str)
    has_score = (ctx.str.len() > 0) & (~ctx.isin(["", "nan", "None"]))

    per_match = df.groupby("match_id").size()
    phase_counts = df["comment_phase"].value_counts().to_dict()

    summary = {
        "db_path": str(db_path.resolve()),
        "n_comments": int(len(df)),
        "n_matches": int(df["match_id"].nunique()),
        "comments_per_match": {
            "min": int(per_match.min()) if len(per_match) else 0,
            "max": int(per_match.max()) if len(per_match) else 0,
            "mean": float(per_match.mean()) if len(per_match) else 0.0,
            "median": float(per_match.median()) if len(per_match) else 0.0,
        },
        "weak_label_counts": {names[i]: int(weak_counts[i]) for i in (0, 1, 2)},
        "gold_labeled_comments": gold_n,
        "posted_at_unix_nonnull_fraction": float(ts_valid.mean()),
        "score_context_nonempty_fraction": float(has_score.mean()),
        "comment_phase_counts": {str(k): int(v) for k, v in phase_counts.items()},
    }

    if ts_valid.any():
        tmin = float(ts[ts_valid].astype(float).min())
        tmax = float(ts[ts_valid].astype(float).max())
        summary["posted_at_unix_range"] = {"min": tmin, "max": tmax, "span_seconds": tmax - tmin}
    else:
        summary["posted_at_unix_range"] = None

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote %s", args.out_json)

    args.figures_dir.mkdir(parents=True, exist_ok=True)

    # Figure: weak label distribution
    fig, ax = plt.subplots(figsize=(5, 3.5))
    labs = [names[i] for i in (0, 1, 2)]
    ax.bar(labs, [weak_counts[i] for i in (0, 1, 2)], color=["#c44e52", "#8172b3", "#55a868"])
    ax.set_ylabel("Count")
    ax.set_title("Weak label distribution (lexicon)")
    plt.tight_layout()
    p1 = args.figures_dir / "dataset_weak_label_counts.png"
    fig.savefig(p1, dpi=120)
    plt.close(fig)
    logger.info("Wrote %s", p1)

    # Figure: comments per match histogram
    fig, ax = plt.subplots(figsize=(5, 3.5))
    arr = per_match.to_numpy()
    ax.hist(arr, bins=min(30, max(5, len(np.unique(arr)))), color="#4c72b0", edgecolor="white")
    ax.set_xlabel("Comments per match")
    ax.set_ylabel("Matches")
    ax.set_title("Comments per match")
    plt.tight_layout()
    p2 = args.figures_dir / "dataset_comments_per_match_hist.png"
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    logger.info("Wrote %s", p2)

    # Figure: comment phase
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ph_keys = list(phase_counts.keys())
    ph_vals = [phase_counts[k] for k in ph_keys]
    ax.bar([str(k) for k in ph_keys], ph_vals, color="#dd8452")
    ax.set_ylabel("Comments")
    ax.set_title("Comment phase (time vs match window)")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    p3 = args.figures_dir / "dataset_comment_phase.png"
    fig.savefig(p3, dpi=120)
    plt.close(fig)
    logger.info("Wrote %s", p3)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
