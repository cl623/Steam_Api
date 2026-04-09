"""
Load comments from hltv_sentiment.db and build train/val/test splits.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Literal, Optional, Tuple

import numpy as np
import pandas as pd

from .preprocess import clean_text
from .weak_labels import label_to_id, weak_sentiment_label

SplitMode = Literal["random", "by_match", "by_time"]
LabelSource = Literal["weak", "gold", "hybrid"]


def default_db_path(project_root: Optional[Path] = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[1]
    return root / "data" / "hltv_sentiment.db"


def load_comments_dataframe(
    db_path: Path,
    *,
    min_chars: int = 2,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Return raw_text, match_id, posted_at_unix, score_context, comment_id."""
    q = """
        SELECT c.match_id, c.comment_id, c.raw_text, c.posted_at_unix, c.score_context,
               c.gold_label
        FROM hltv_comments c
        WHERE LENGTH(TRIM(c.raw_text)) >= ?
        ORDER BY c.match_id, c.posted_at_unix, c.comment_id
    """
    with sqlite3.connect(str(db_path)) as conn:
        df = pd.read_sql_query(q, conn, params=(min_chars,))
    if limit is not None:
        df = df.head(limit)
    return df


def add_weak_labels(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["clean_text"] = out["raw_text"].astype(str).map(clean_text)
    out["label_name"] = out["raw_text"].astype(str).map(weak_sentiment_label)
    out["weak_label"] = out["label_name"].map(label_to_id)
    out["label"] = out["weak_label"]
    return out


def apply_label_source(df: pd.DataFrame, source: LabelSource) -> pd.DataFrame:
    """
    weak: train/eval on lexicon weak labels.
    gold: only rows with non-null gold_label (hand labels).
    hybrid: gold where present, else weak (semi-supervised training).
    """
    out = df.copy()
    if "weak_label" not in out.columns:
        out = add_weak_labels(out)
    if "gold_label" not in out.columns:
        out["gold_label"] = np.nan
    else:
        out["gold_label"] = pd.to_numeric(out["gold_label"], errors="coerce")

    if source == "weak":
        out["label"] = out["weak_label"]
    elif source == "gold":
        out = out[out["gold_label"].notna()].copy()
        out["label"] = out["gold_label"].astype(int)
    elif source == "hybrid":
        out["label"] = (
            out["gold_label"].where(out["gold_label"].notna(), out["weak_label"]).astype(int)
        )
    else:
        raise ValueError(f"Unknown label source: {source}")
    return out


def train_val_test_split(
    df: pd.DataFrame,
    *,
    mode: SplitMode = "by_match",
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
    random_state: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split rows. For by_match, all rows of a match stay in one split.
    For by_time, sorts by posted_at_unix (missing last) and takes contiguous slices.
    """
    if df.empty:
        return df.copy(), df.copy(), df.copy()

    rng = np.random.default_rng(random_state)

    if mode == "random":
        idx = np.arange(len(df))
        rng.shuffle(idx)
        n = len(idx)
        n_test = int(round(n * test_fraction))
        n_val = int(round(n * val_fraction))
        test_idx = idx[:n_test]
        val_idx = idx[n_test : n_test + n_val]
        train_idx = idx[n_test + n_val :]
        return (
            df.iloc[train_idx].reset_index(drop=True),
            df.iloc[val_idx].reset_index(drop=True),
            df.iloc[test_idx].reset_index(drop=True),
        )

    if mode == "by_match":
        matches = list(df["match_id"].unique())
        rng.shuffle(matches)
        n_m = len(matches)
        if n_m == 0:
            z = df.iloc[:0]
            return z.copy(), z.copy(), z.copy()
        n_test = int(round(n_m * test_fraction))
        n_val = int(round(n_m * val_fraction))
        n_test = max(0, min(n_test, n_m - 1))
        n_val = max(0, min(n_val, max(0, n_m - n_test - 1)))
        while n_test + n_val >= n_m and (n_test > 0 or n_val > 0):
            if n_val > 0:
                n_val -= 1
            elif n_test > 0:
                n_test -= 1
        test_m = set(matches[:n_test])
        val_m = set(matches[n_test : n_test + n_val])
        train_m = set(matches[n_test + n_val :])
        train_df = df[df["match_id"].isin(train_m)]
        val_df = df[df["match_id"].isin(val_m)]
        test_df = df[df["match_id"].isin(test_m)]
        return (
            train_df.reset_index(drop=True),
            val_df.reset_index(drop=True),
            test_df.reset_index(drop=True),
        )

    # by_time
    d = df.copy()
    d["_ts"] = d["posted_at_unix"].fillna(-1)
    d = d.sort_values("_ts")
    n = len(d)
    n_test = int(round(n * test_fraction))
    n_val = int(round(n * val_fraction))
    test_df = d.iloc[-n_test:] if n_test else d.iloc[:0]
    val_df = d.iloc[-n_test - n_val : -n_test] if n_val else d.iloc[:0]
    train_df = d.iloc[: -n_test - n_val] if (n_test + n_val) else d
    return (
        train_df.drop(columns=["_ts"]).reset_index(drop=True),
        val_df.drop(columns=["_ts"]).reset_index(drop=True),
        test_df.drop(columns=["_ts"]).reset_index(drop=True),
    )


def split_meta_dict(
    mode: SplitMode,
    val_fraction: float,
    test_fraction: float,
    random_state: int,
    n_train: int,
    n_val: int,
    n_test: int,
) -> dict[str, Any]:
    return {
        "split_mode": mode,
        "val_fraction": val_fraction,
        "test_fraction": test_fraction,
        "random_state": random_state,
        "n_train": n_train,
        "n_val": n_val,
        "n_test": n_test,
    }
