#!/usr/bin/env python
"""Evaluate NB or LSTM: F1, confusion matrix PNG, optional velocity vs swing proxy."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix, f1_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from nlp.dataset import (  # noqa: E402
    add_weak_labels,
    default_db_path,
    load_comments_dataframe,
    train_val_test_split,
)
from nlp.models_lstm import encode_texts, load_lstm_bundle  # noqa: E402
from nlp.velocity import (  # noqa: E402
    pearson_spearman,
    scores_from_probs,
    swing_labels_from_context,
    velocity_per_bin,
)

logger = logging.getLogger("eval_sentiment")


def _probs_nb(pipe, texts: list[str]) -> np.ndarray:
    """Map predict_proba columns to fixed [neg, neu, pos] = indices 0,1,2."""
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
    ap.add_argument("--model-type", choices=("nb", "lstm"), default="nb")
    ap.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="nb: .joblib path; lstm: .pt bundle",
    )
    ap.add_argument("--split-mode", choices=("random", "by_match", "by_time"), default="by_match")
    ap.add_argument("--test-fraction", type=float, default=0.15)
    ap.add_argument("--val-fraction", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "sentiment_eval",
    )
    ap.add_argument("--velocity-bin-seconds", type=float, default=120.0)
    ap.add_argument(
        "--label-source",
        choices=("weak", "gold"),
        default="weak",
        help="weak=lexicon truth; gold=only hand-labeled rows in eval split",
    )
    args = ap.parse_args()

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        logger.error("DB missing: %s", db_path)
        return 1

    raw = load_comments_dataframe(db_path, limit=args.limit)
    if raw.empty:
        logger.error("No comments.")
        return 1
    df = add_weak_labels(raw)
    tr, va, te = train_val_test_split(
        df,
        mode=args.split_mode,
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        random_state=args.seed,
    )
    part = te if not te.empty else df
    if args.label_source == "gold":
        part = part[part["gold_label"].notna()].copy()
        if part.empty:
            logger.error("No gold-labeled rows in eval split; use weak or label more data.")
            return 1
        y_true = part["gold_label"].astype(int).to_numpy()
    else:
        y_true = part["label"].to_numpy()
    texts = part["raw_text"].astype(str).tolist()

    if args.model_type == "nb":
        ckpt = args.checkpoint or (PROJECT_ROOT / "sentiment_models" / "nb" / "nb_unigram.joblib")
        if not ckpt.is_file():
            logger.error("NB model not found: %s", ckpt)
            return 1
        pipe = joblib.load(ckpt)
        probs = _probs_nb(pipe, texts)
        y_pred = probs.argmax(axis=1)
    else:
        ckpt = args.checkpoint or (PROJECT_ROOT / "sentiment_models" / "lstm" / "lstm_weak.pt")
        if not ckpt.is_file():
            logger.error("LSTM bundle not found: %s", ckpt)
            return 1
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, stoi, max_len = load_lstm_bundle(ckpt, map_location=str(device))
        probs = _probs_lstm(model, stoi, max_len, texts, device)
        y_pred = probs.argmax(axis=1)

    labels = [0, 1, 2]
    names = ["neg", "neu", "pos"]
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    report = classification_report(y_true, y_pred, labels=labels, target_names=names, zero_division=0)
    f1_macro = float(f1_score(y_true, y_pred, average="macro", zero_division=0))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(cm, interpolation="nearest")
    plt.colorbar(im, ax=ax)
    ax.set_xticks(range(3))
    ax.set_yticks(range(3))
    ax.set_xticklabels(names)
    ax.set_yticklabels(names)
    ax.set_ylabel("True")
    ax.set_xlabel("Predicted")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center")
    plt.tight_layout()
    cm_path = (
        args.out_dir
        / f"confusion_{args.model_type}_{args.label_source}.png"
    )
    fig.savefig(cm_path, dpi=120)
    plt.close(fig)

    # velocity vs swing (per match, aggregate correlation)
    sent_scores = scores_from_probs(probs)
    ts = part["posted_at_unix"].to_numpy(dtype=np.float64)
    ctx = part["score_context"].tolist()

    vel_df = velocity_per_bin(ts, sent_scores, bin_seconds=args.velocity_bin_seconds)
    swings = swing_labels_from_context([str(c) if c is not None else "" for c in ctx])

    pearson_r, spearman_r = pearson_spearman(sent_scores.astype(float), swings.astype(float))

    summary = {
        "f1_macro": f1_macro,
        "confusion_matrix": cm.tolist(),
        "classification_report": report,
        "n_eval": int(len(part)),
        "velocity_bin_seconds": args.velocity_bin_seconds,
        "velocity_mean": float(vel_df["velocity"].dropna().mean())
        if not vel_df.empty
        else None,
        "correlation_sentiment_score_vs_swing_proxy_pearson": pearson_r,
        "correlation_sentiment_score_vs_swing_proxy_spearman": spearman_r,
        "label_source": args.label_source,
        "note": "Swing proxy uses score_context round-diff heuristic; y_true follows label_source.",
    }
    out_json = args.out_dir / f"metrics_{args.model_type}_{args.label_source}.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote %s and %s", cm_path, out_json)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
