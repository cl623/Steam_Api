"""
Sentiment velocity: change in average sentiment score over time windows.
Correlate with simple binary "swing" proxies derived from score_context strings.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


def scores_from_probs(probs: np.ndarray) -> np.ndarray:
    """Map class probs [neg, neu, pos] to scalar score in [-1, 1]."""
    # probs: (n, 3)
    if probs.ndim != 2 or probs.shape[1] != 3:
        raise ValueError("probs must be (n, 3) for neg/neu/pos")
    w = np.array([-1.0, 0.0, 1.0], dtype=np.float64)
    return (probs * w).sum(axis=1)


def scores_from_labels(labels: np.ndarray) -> np.ndarray:
    """Hard labels 0,1,2 -> [-1,0,1]."""
    m = np.array([-1.0, 0.0, 1.0])
    return m[labels.astype(int)]


def velocity_per_bin(
    timestamps: np.ndarray,
    sentiment_scores: np.ndarray,
    *,
    bin_seconds: float = 120.0,
) -> pd.DataFrame:
    """
    Sort by time, bucket into bins of width bin_seconds (unix),
    compute mean sentiment per bin and Δmean/Δt between consecutive bins.
    Rows with NaN timestamp are dropped.
    """
    ts = timestamps.astype(np.float64)
    sc = sentiment_scores.astype(np.float64)
    mask = np.isfinite(ts)
    ts, sc = ts[mask], sc[mask]
    if len(ts) == 0:
        return pd.DataFrame(columns=["bin_start", "mean_s", "velocity", "delta_t"])

    order = np.argsort(ts)
    ts, sc = ts[order], sc[order]
    bin_idx = np.floor((ts - ts.min()) / bin_seconds).astype(int)
    rows = []
    for b in range(bin_idx.max() + 1):
        sel = bin_idx == b
        if not np.any(sel):
            continue
        rows.append(
            {
                "bin_start": ts.min() + b * bin_seconds,
                "mean_s": float(sc[sel].mean()),
                "count": int(sel.sum()),
            }
        )
    df = pd.DataFrame(rows)
    if len(df) < 2:
        df["velocity"] = np.nan
        df["delta_t"] = np.nan
        return df
    df = df.sort_values("bin_start")
    df["velocity"] = df["mean_s"].diff() / df["bin_start"].diff().replace(0, np.nan)
    df["delta_t"] = df["bin_start"].diff()
    return df.reset_index(drop=True)


_SCORE_PAIR = re.compile(r"(\d+)\s*[-:]\s*(\d+)")


def parse_round_differential(score_context: str) -> Optional[float]:
    """
    Best-effort parse '14-12' or '16:14' style into team1 - team2.
    Returns None if not parseable.
    """
    if not score_context or not isinstance(score_context, str):
        return None
    m = _SCORE_PAIR.search(score_context.replace(";", " "))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return float(a - b)


def swing_labels_from_context(
    contexts: List[Optional[str]],
    *,
    threshold: float = 3.0,
    lookahead: int = 5,
) -> np.ndarray:
    """
    For each position i, label 1 if |diff_{i+k} - diff_i| >= threshold for some
    k in 1..lookahead (diff from parse_round_differential). Else 0.
    """
    diffs = np.array([parse_round_differential(c or "") for c in contexts], dtype=float)
    n = len(diffs)
    out = np.zeros(n, dtype=int)
    for i in range(n):
        base = diffs[i]
        if not np.isfinite(base):
            continue
        for k in range(1, min(lookahead, n - i - 1) + 1):
            nxt = diffs[i + k]
            if np.isfinite(nxt) and abs(nxt - base) >= threshold:
                out[i] = 1
                break
    return out


def pearson_spearman(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """Return (pearson_r, spearman_r) skipping non-finite pairs."""
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan"), float("nan")
    a, b = x[m], y[m]
    pear = float(np.corrcoef(a, b)[0, 1])
    sdf = pd.DataFrame({"a": a, "b": b})
    spear = float(sdf["a"].corr(sdf["b"], method="spearman"))
    return pear, spear


def lag_shift_correlation(
    x: np.ndarray,
    y: np.ndarray,
    lag: int,
) -> Tuple[float, float]:
    """
    Correlate x[t] with y[t+lag] (forward shift of y by `lag` steps).
    Both arrays same length, ordered by time within a match.
    """
    if lag < 0:
        raise ValueError("lag must be non-negative")
    if lag == 0:
        return pearson_spearman(x.astype(float), y.astype(float))
    if len(x) <= lag:
        return float("nan"), float("nan")
    return pearson_spearman(x[:-lag].astype(float), y[lag:].astype(float))


def mean_abs_velocity(
    timestamps: np.ndarray,
    sentiment_scores: np.ndarray,
    bin_seconds: float,
) -> float:
    df = velocity_per_bin(timestamps, sentiment_scores, bin_seconds=bin_seconds)
    v = df["velocity"].dropna()
    if v.empty:
        return float("nan")
    return float(v.abs().mean())
