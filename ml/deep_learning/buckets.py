"""Return-bucket definitions for the classification approach (V3.0 Phase 2).

The Steam Community Market charges ~15% in fees (publisher + Steam cut).
Bucket boundaries are defined in **log-return** space so they align with
the target transformation used by the Phase 1 pipeline.

    log_return ≈ sign(r) * log(1 + |r|)

The four trading-relevant buckets:

    LARGE_DROP    – significant price decline (log-return < -0.15)
    FLAT          – sideways / losing after fees (-0.15 ≤ lr < 0.14)
    BREAK_EVEN    – covers the ~15% fee, modest profit (0.14 ≤ lr < 0.40)
    MASSIVE_SPIKE – major profit opportunity (lr ≥ 0.40)

These thresholds are configurable via ``BUCKET_EDGES``.
"""

from __future__ import annotations

from typing import List, Sequence

import numpy as np
import torch

# ── bucket definitions ──────────────────────────────────────────────────────

BUCKET_NAMES: List[str] = [
    "Large Drop",
    "Flat / Sideways",
    "Break-Even",
    "Massive Spike",
]

NUM_BUCKETS = len(BUCKET_NAMES)

# Edges between buckets (in log-return space).  len = NUM_BUCKETS - 1.
# A sample with log_return < BUCKET_EDGES[0] → bucket 0, etc.
BUCKET_EDGES: List[float] = [-0.15, 0.14, 0.40]


# ── conversion utilities ───────────────────────────────────────────────────

def log_return_to_bucket(log_return: float) -> int:
    """Map a single log-return value to its bucket index (0-based)."""
    for i, edge in enumerate(BUCKET_EDGES):
        if log_return < edge:
            return i
    return len(BUCKET_EDGES)


def log_returns_to_labels(log_returns: Sequence[float]) -> np.ndarray:
    """Vectorised conversion of log-return values to bucket labels."""
    arr = np.asarray(log_returns, dtype=np.float32)
    labels = np.digitize(arr, bins=BUCKET_EDGES).astype(np.int64)
    return labels


def labels_to_tensor(log_returns: Sequence[float]) -> torch.LongTensor:
    """Convert log-returns directly to a ``LongTensor`` of bucket labels."""
    return torch.from_numpy(log_returns_to_labels(log_returns))


def bucket_midpoints() -> np.ndarray:
    """Return the representative midpoint log-return for each bucket.

    Useful for converting a predicted bucket back to an approximate
    continuous log-return (e.g. for back-testing integration).
    """
    edges = [-np.inf] + BUCKET_EDGES + [np.inf]
    mids = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        if np.isinf(lo):
            mids.append(hi - 0.20)
        elif np.isinf(hi):
            mids.append(lo + 0.30)
        else:
            mids.append((lo + hi) / 2.0)
    return np.array(mids, dtype=np.float32)


def bucket_distribution(log_returns: Sequence[float]) -> dict:
    """Return {bucket_name: count} for a set of log-return targets."""
    labels = log_returns_to_labels(log_returns)
    dist = {}
    for i, name in enumerate(BUCKET_NAMES):
        dist[name] = int((labels == i).sum())
    return dist


def clipped_returns_to_log_returns(
    returns: np.ndarray,
    max_abs: float = 3.0,
) -> np.ndarray:
    """Match ``dataset`` target: clip percentage returns then signed log1p."""
    r = np.asarray(returns, dtype=np.float64)
    c = np.clip(r, -max_abs, max_abs)
    return (np.sign(c) * np.log1p(np.abs(c))).astype(np.float32)


def returns_to_bucket_labels(returns: np.ndarray, max_abs: float = 3.0) -> np.ndarray:
    """Bucket labels for clipped percentage returns (tabular models)."""
    lr = clipped_returns_to_log_returns(returns, max_abs=max_abs)
    return log_returns_to_labels(lr)


def expected_log_return_from_probs(probs: np.ndarray) -> np.ndarray:
    """``probs`` (N, K) softmax; return N expected log-returns using ``bucket_midpoints``."""
    mids = bucket_midpoints().astype(np.float64)
    return (probs.astype(np.float64) @ mids).astype(np.float32)
