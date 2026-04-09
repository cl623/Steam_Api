#!/usr/bin/env python3
"""
Validate time-sync quality for pre/during/post analysis.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from nlp.dataset import default_db_path, load_comments_dataframe  # noqa: E402
from nlp.time_windows import add_comment_phase  # noqa: E402
from nlp.velocity import score_context_round_index  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "sentiment_eval" / "time_sync_report.json",
    )
    ap.add_argument(
        "--min-known-phase-rate",
        type=float,
        default=0.70,
        help="Warn if known phase (pre/during/post) is below this rate.",
    )
    args = ap.parse_args()

    db_path = args.db or default_db_path()
    if not db_path.is_file():
        print(f"DB missing: {db_path}")
        return 1

    df = load_comments_dataframe(db_path, include_match_windows=True)
    if df.empty:
        print("No comments in DB.")
        return 1
    if "comment_phase" not in df.columns:
        df = add_comment_phase(df)

    n = len(df)
    pct_posted = float(df["posted_at_unix"].notna().mean())
    pct_start = float(df["match_start_unix"].notna().mean()) if "match_start_unix" in df.columns else 0.0
    pct_end = float(df["match_end_unix"].notna().mean()) if "match_end_unix" in df.columns else 0.0
    phase_counts = df["comment_phase"].value_counts(dropna=False).to_dict()
    known_phase_rate = float((df["comment_phase"] != "unknown").mean())

    round_idx = np.array(
        [score_context_round_index(str(c) if c is not None else "") for c in df["score_context"].tolist()],
        dtype=float,
    )
    pct_score_parse = float(np.isfinite(round_idx).mean())

    report = {
        "n_comments": int(n),
        "pct_with_posted_at_unix": pct_posted,
        "pct_with_match_start_unix": pct_start,
        "pct_with_match_end_unix": pct_end,
        "pct_with_parseable_score_context_round_index": pct_score_parse,
        "comment_phase_counts": {str(k): int(v) for k, v in phase_counts.items()},
        "known_phase_rate": known_phase_rate,
        "warnings": [],
    }
    if known_phase_rate < args.min_known_phase_rate:
        report["warnings"].append(
            f"known_phase_rate {known_phase_rate:.3f} below threshold {args.min_known_phase_rate:.3f}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
