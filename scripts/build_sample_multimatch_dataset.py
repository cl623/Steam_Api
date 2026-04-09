#!/usr/bin/env python3
"""
Write samples/hltv_comments_multimatch.jsonl and samples/gold_labels_example.csv.

Synthetic multi-match thread data for local testing (not real HLTV text).
Run from repo root: python scripts/build_sample_multimatch_dataset.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT_ROOT / "samples"

# (text, weak vibe for gold sampling)
TEMPLATES = [
    ("insane clutch from player one", 2),
    ("nice try wp boys", 2),
    ("this team is so good love it", 2),
    ("terrible throw holy moly", 0),
    ("disband already trash performance", 0),
    ("maybe next map idk", 1),
    ("eco round inc", 1),
    ("force buy here", 1),
    ("choke city unbelievable", 0),
    ("pog moment", 2),
    ("bots running it down", 0),
    ("calm game so far", 1),
]

SCORES = [
    "8-8",
    "9-8",
    "10-8",
    "11-8",
    "12-10",
    "12-11",
    "13-11",
    "14-11",
    "14-12",
    "15-12",
    "15-14",
    "16-14",
]


def main() -> int:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    jsonl_path = SAMPLES / "hltv_comments_multimatch.jsonl"
    csv_path = SAMPLES / "gold_labels_example.csv"

    match_ids = [91001, 91002, 91003, 91004, 91005]
    gold_rows: list[tuple[int, str, str]] = []

    with jsonl_path.open("w", encoding="utf-8") as jf:
        for mid in match_ids:
            base_t = 1_700_000_000 + mid * 1_000
            for i in range(len(TEMPLATES)):
                txt, vibe = TEMPLATES[i]
                sc = SCORES[i % len(SCORES)]
                cid = f"{mid}-{i}"
                row = {
                    "match_id": mid,
                    "comment_id": cid,
                    "raw_text": f"{txt} (match {mid})",
                    "posted_at_unix": base_t + i * 75,
                    "score_context": sc,
                }
                jf.write(json.dumps(row, ensure_ascii=False) + "\n")
                # Gold labels for ~half the comments (spread across matches)
                if i % 2 == 0:
                    name = ("neg", "neu", "pos")[vibe]
                    gold_rows.append((mid, cid, name))

    with csv_path.open("w", newline="", encoding="utf-8") as cf:
        w = csv.writer(cf)
        w.writerow(["match_id", "comment_id", "label"])
        w.writerows(gold_rows)

    print(f"Wrote {jsonl_path} and {csv_path} ({len(gold_rows)} gold rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
