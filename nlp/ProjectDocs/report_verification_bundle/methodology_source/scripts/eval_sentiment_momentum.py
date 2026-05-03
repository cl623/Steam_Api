#!/usr/bin/env python
"""
Per-match sentiment velocity, multi bin widths, and lag sweep vs swing proxy.

Uses all comments in DB (or --limit) ordered by time within each match.
Model checkpoint should be trained separately (NB joblib or LSTM .pt bundle).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from nlp.dataset import add_weak_labels, default_db_path, load_comments_dataframe  # noqa: E402
from nlp.models_lstm import encode_texts, load_lstm_bundle  # noqa: E402
from nlp.time_windows import add_comment_phase  # noqa: E402
from nlp.velocity import (  # noqa: E402
    lag_shift_correlation,
    mean_abs_velocity,
    score_context_round_index,
    scores_from_probs,
    swing_labels_from_context,
)

logger = logging.getLogger("eval_momentum")


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
    ap.add_argument("--model-type", choices=("nb", "lstm"), default="nb")
    ap.add_argument("--checkpoint", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--phase",
        choices=("during", "pre", "post", "all"),
        default="during",
        help="Comment phase to analyze (default: during).",
    )
    ap.add_argument(
        "--allow-unknown-phase",
        action="store_true",
        help="Include comments with unknown phase classification.",
    )
    ap.add_argument(
        "--time-axis",
        choices=("seconds", "round_bin"),
        default="seconds",
        help="Use posted_at_unix or score_context-derived round bins.",
    )
    ap.add_argument(
        "--bin-seconds",
        type=str,
        default="60,120,180,300",
        help="Comma-separated velocity bin widths",
    )
    ap.add_argument(
        "--lag-steps",
        type=str,
        default="0,1,2,3,5,8",
        help="Forward lag in comment indices (within each match)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "sentiment_eval" / "momentum_report.json",
    )
    args = ap.parse_args()

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        logger.error("DB missing: %s", db_path)
        return 1

    raw = load_comments_dataframe(db_path, limit=args.limit)
    if raw.empty:
        logger.error("No comments")
        return 1
    df = add_weak_labels(raw)
    if "comment_phase" not in df.columns:
        df = add_comment_phase(df)

    if args.phase != "all":
        allowed = {args.phase}
        if args.allow_unknown_phase:
            allowed.add("unknown")
        df = df[df["comment_phase"].isin(allowed)].copy()
    elif not args.allow_unknown_phase:
        df = df[df["comment_phase"] != "unknown"].copy()
    if df.empty:
        logger.error("No comments after phase filtering.")
        return 1
    texts = df["raw_text"].astype(str).tolist()

    if args.model_type == "nb":
        ckpt = args.checkpoint or (PROJECT_ROOT / "sentiment_models" / "nb" / "nb_unigram.joblib")
        if not ckpt.is_file():
            logger.error("NB model not found: %s", ckpt)
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
    df = df.assign(_pred_score=scores)

    bins = [float(x.strip()) for x in args.bin_seconds.split(",") if x.strip()]
    lags = [int(x.strip()) for x in args.lag_steps.split(",") if x.strip()]

    per_match = []
    agg_lag_pear: dict[int, list[float]] = {lag: [] for lag in lags}
    agg_lag_spear: dict[int, list[float]] = {lag: [] for lag in lags}
    agg_mabs: dict[float, list[float]] = {b: [] for b in bins}

    for mid, g in df.groupby("match_id", sort=False):
        g = g.sort_values(
            by=["posted_at_unix", "comment_id"],
            ascending=[True, True],
            na_position="last",
        )
        ts = g["posted_at_unix"].to_numpy(dtype=np.float64)
        if args.time_axis == "round_bin":
            round_idx = np.array(
                [
                    score_context_round_index(str(c) if c is not None else "")
                    for c in g["score_context"].tolist()
                ],
                dtype=float,
            )
            # Fall back to index order when round parse fails entirely
            if np.isfinite(round_idx).sum() == 0:
                round_idx = np.arange(len(g), dtype=float)
            ts = round_idx
        sc = g["_pred_score"].to_numpy(dtype=np.float64)
        ctx = g["score_context"].tolist()
        swings = swing_labels_from_context(
            [str(c) if c is not None else "" for c in ctx]
        ).astype(float)
        if len(sc) < 4:
            continue
        row = {"match_id": int(mid), "n": int(len(sc))}
        for b in bins:
            mabs = mean_abs_velocity(ts, sc, b)
            row[f"mean_abs_velocity_{int(b)}s"] = mabs
            if np.isfinite(mabs):
                agg_mabs[b].append(mabs)
        for lag in lags:
            pe, sp = lag_shift_correlation(sc, swings, lag)
            row[f"lag{lag}_pearson"] = pe
            row[f"lag{lag}_spearman"] = sp
            if np.isfinite(pe):
                agg_lag_pear[lag].append(pe)
            if np.isfinite(sp):
                agg_lag_spear[lag].append(sp)
        per_match.append(row)

    def _mean(xs: list[float]) -> float:
        return float(np.nanmean(xs)) if xs else float("nan")

    summary = {
        "model_type": args.model_type,
        "phase": args.phase,
        "allow_unknown_phase": bool(args.allow_unknown_phase),
        "time_axis": args.time_axis,
        "n_comments": int(len(df)),
        "n_matches_analyzed": len(per_match),
        "aggregate_mean_abs_velocity": {str(int(b)): _mean(agg_mabs[b]) for b in bins},
        "aggregate_lag_pearson_mean": {str(lag): _mean(agg_lag_pear[lag]) for lag in lags},
        "aggregate_lag_spearman_mean": {str(lag): _mean(agg_lag_spear[lag]) for lag in lags},
        "per_match": per_match,
        "note": "Swing proxy from score_context; lags are comment-index offsets within match.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
