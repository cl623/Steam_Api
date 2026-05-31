#!/usr/bin/env python
"""
One-match plot: binned mean sentiment score and velocity vs time (exemplar figure for reports).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from nlp.dataset import add_weak_labels, default_db_path, load_comments_dataframe  # noqa: E402
from nlp.models_lstm import encode_texts, load_lstm_bundle  # noqa: E402
from nlp.time_windows import add_comment_phase  # noqa: E402
from nlp.velocity import scores_from_probs, velocity_per_bin  # noqa: E402

logger = logging.getLogger("plot_exemplar")


def _probs_nb(pipe, texts: list[str]) -> np.ndarray:
    clf = pipe.named_steps["clf"]
    classes = clf.classes_
    p = pipe.predict_proba(texts)
    out = np.zeros((len(texts), 3), dtype=np.float64)
    for j, c in enumerate(classes):
        ci = int(c)
        if 0 <= ci < 3:
            out[:, ci] = p[:, j]
    return out


def _probs_lstm(model, stoi, max_len, texts: list[str], device: torch.device) -> np.ndarray:
    x = encode_texts(texts, stoi, max_len)
    model.eval()
    model.to(device)
    out = []
    with torch.no_grad():
        for i in range(0, len(x), 64):
            batch = torch.tensor(x[i : i + 64], dtype=torch.long, device=device)
            logits = model(batch)
            pr = torch.softmax(logits, dim=1).cpu().numpy()
            out.append(pr)
    return np.vstack(out)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--match-id", type=int, default=None, help="Default: match with most comments")
    ap.add_argument("--model-type", choices=("nb", "lstm"), default="nb")
    ap.add_argument("--checkpoint", type=Path, default=None)
    ap.add_argument("--phase", choices=("during", "pre", "post", "all"), default="during")
    ap.add_argument("--bin-seconds", type=float, default=120.0)
    ap.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "nlp" / "ProjectDocs" / "figures" / "exemplar_match_velocity.png",
    )
    args = ap.parse_args()

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        logger.error("DB missing: %s", db_path)
        return 1

    raw = load_comments_dataframe(db_path)
    if raw.empty:
        logger.error("No comments")
        return 1
    df = add_weak_labels(raw)
    df = add_comment_phase(df)

    if args.phase != "all":
        df = df[df["comment_phase"] == args.phase].copy()
    if df.empty:
        logger.error("No rows after phase filter")
        return 1

    mid = args.match_id
    if mid is None:
        counts = df.groupby("match_id").size()
        mid = int(counts.idxmax())
        logger.info("Using match_id=%s (max comments in split)", mid)

    g = df[df["match_id"] == mid].sort_values(
        ["posted_at_unix", "comment_id"], ascending=[True, True], na_position="last"
    )
    if len(g) < 4:
        logger.error("Too few comments for match %s", mid)
        return 1

    texts = g["raw_text"].astype(str).tolist()
    if args.model_type == "nb":
        ckpt = args.checkpoint or (PROJECT_ROOT / "sentiment_models" / "nb" / "nb_unigram.joblib")
        if not ckpt.is_file():
            logger.error("NB checkpoint missing: %s", ckpt)
            return 1
        pipe = joblib.load(ckpt)
        probs = _probs_nb(pipe, texts)
    else:
        ckpt = args.checkpoint or (PROJECT_ROOT / "sentiment_models" / "lstm" / "lstm_weak.pt")
        if not ckpt.is_file():
            logger.error("LSTM bundle missing: %s", ckpt)
            return 1
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, stoi, max_len = load_lstm_bundle(ckpt, map_location=str(device))
        probs = _probs_lstm(model, stoi, max_len, texts, device)

    scores = scores_from_probs(probs)
    ts = g["posted_at_unix"].to_numpy(dtype=np.float64)
    if not np.isfinite(ts).all() or np.nanmin(ts) == np.nanmax(ts):
        ts = np.arange(len(scores), dtype=np.float64)
        logger.warning("posted_at_unix missing or flat; using comment index as time axis")

    vdf = velocity_per_bin(ts, scores, bin_seconds=args.bin_seconds)
    if vdf.empty or vdf["mean_s"].notna().sum() < 2:
        logger.error("Velocity dataframe too sparse")
        return 1

    t0 = float(vdf["bin_start"].min())
    t_rel = (vdf["bin_start"] - t0) / 60.0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.plot(t_rel, vdf["mean_s"], "o-", color="#4c72b0", label="Mean sentiment score [-1,1]")
    ax1.set_xlabel("Minutes from first bin")
    ax1.set_ylabel("Mean sentiment")
    ax1.axhline(0.0, color="gray", linewidth=0.6, linestyle=":")
    ax2 = ax1.twinx()
    ax2.plot(t_rel, vdf["velocity"], "s--", color="#c44e52", alpha=0.85, label="Velocity (Δscore/Δt)")
    ax2.set_ylabel("Velocity")
    ax1.set_title(f"Exemplar match {mid} — {args.model_type.upper()} scores, {args.bin_seconds:.0f}s bins")
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="upper right", fontsize=8)
    plt.tight_layout()
    fig.savefig(args.out, dpi=120)
    plt.close(fig)
    logger.info("Wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
