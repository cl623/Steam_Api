#!/usr/bin/env python
"""Plot aggregate lag correlations from eval_sentiment_momentum.py JSON output."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

logger = logging.getLogger("plot_momentum")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        type=Path,
        required=True,
        help="momentum_report.json from eval_sentiment_momentum.py",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Defaults to parent of input / figures_momentum",
    )
    args = ap.parse_args()

    if not args.input.is_file():
        logger.error("Missing input: %s", args.input)
        return 1

    data = json.loads(args.input.read_text(encoding="utf-8"))
    out_dir = args.out_dir or (args.input.parent / "figures_momentum")
    out_dir.mkdir(parents=True, exist_ok=True)

    pear = data.get("aggregate_lag_pearson_mean") or {}
    spear = data.get("aggregate_lag_spearman_mean") or {}
    lags = sorted(int(k) for k in pear.keys() if k in spear)
    if not lags:
        logger.error("No lag keys in JSON")
        return 1

    y1 = [float(pear[str(l)]) for l in lags]
    y2 = [float(spear[str(l)]) for l in lags]

    x = np.arange(len(lags))
    w = 0.35
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(x - w / 2, y1, width=w, label="Pearson r (mean over matches)", color="#4c72b0")
    ax.bar(x + w / 2, y2, width=w, label="Spearman ρ (mean over matches)", color="#55a868")
    ax.set_xticks(x)
    ax.set_xticklabels([str(l) for l in lags])
    ax.set_xlabel("Lag (comment indices within match)")
    ax.set_ylabel("Correlation (pred score vs swing proxy)")
    ax.axhline(0.0, color="gray", linewidth=0.8, linestyle="--")
    ax.set_title(
        f"Sentiment score vs momentum swing proxy — {data.get('model_type', '?')} "
        f"({data.get('phase', '?')} phase)"
    )
    ax.legend(loc="upper right", fontsize=8)
    plt.tight_layout()
    p = out_dir / "momentum_lag_correlations.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    logger.info("Wrote %s", p)

    mabs = data.get("aggregate_mean_abs_velocity") or {}
    if mabs:
        bins = sorted(int(k) for k in mabs.keys())
        vals = [float(mabs[str(b)]) for b in bins]
        fig2, ax2 = plt.subplots(figsize=(6, 3.5))
        ax2.bar(np.arange(len(bins)), vals, color="#c44e52")
        ax2.set_xticks(np.arange(len(bins)), labels=[str(b) for b in bins])
        ax2.set_xlabel("Velocity bin width (seconds)")
        ax2.set_ylabel("Mean |velocity| (aggregated)")
        ax2.set_title("Mean absolute sentiment velocity by bin width")
        plt.tight_layout()
        p2 = out_dir / "momentum_mean_abs_velocity.png"
        fig2.savefig(p2, dpi=120)
        plt.close(fig2)
        logger.info("Wrote %s", p2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
