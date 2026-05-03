"""
Time-window helpers for pre/during/post comment phase assignment.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def classify_comment_phase(
    posted_at_unix: Optional[float],
    match_start_unix: Optional[float],
    match_end_unix: Optional[float],
) -> str:
    if posted_at_unix is None or pd.isna(posted_at_unix):
        return "unknown"
    t = float(posted_at_unix)
    has_start = match_start_unix is not None and not pd.isna(match_start_unix)
    has_end = match_end_unix is not None and not pd.isna(match_end_unix)

    if has_start and has_end:
        s = float(match_start_unix)
        e = float(match_end_unix)
        if t < s:
            return "pre"
        if t > e:
            return "post"
        return "during"
    if has_start and not has_end:
        return "pre" if t < float(match_start_unix) else "during"
    if has_end and not has_start:
        return "post" if t > float(match_end_unix) else "during"
    return "unknown"


def add_comment_phase(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["comment_phase"] = out.apply(
        lambda r: classify_comment_phase(
            r.get("posted_at_unix"),
            r.get("match_start_unix"),
            r.get("match_end_unix"),
        ),
        axis=1,
    )
    return out


def filter_during_comments(df: pd.DataFrame) -> pd.DataFrame:
    if "comment_phase" not in df.columns:
        out = add_comment_phase(df)
    else:
        out = df
    return out[out["comment_phase"] == "during"].copy()


def pre_match_subset(df: pd.DataFrame) -> pd.DataFrame:
    if "comment_phase" not in df.columns:
        out = add_comment_phase(df)
    else:
        out = df
    return out[out["comment_phase"] == "pre"].copy()
