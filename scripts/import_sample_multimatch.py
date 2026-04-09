#!/usr/bin/env python3
"""Migrate DB and import samples/hltv_comments_multimatch.jsonl (then optional gold CSV)."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import migrate_hltv_sentiment_db as sentiment_migrate  # noqa: E402
from collector.hltv_comments import import_jsonl_comments  # noqa: E402
from nlp.io_gold import apply_gold_labels_csv  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "hltv_sentiment.db")
    ap.add_argument(
        "--jsonl",
        type=Path,
        default=PROJECT_ROOT / "samples" / "hltv_comments_multimatch.jsonl",
    )
    ap.add_argument(
        "--gold-csv",
        type=Path,
        default=PROJECT_ROOT / "samples" / "gold_labels_example.csv",
        help="Import gold labels after JSONL (default: samples/gold_labels_example.csv)",
    )
    ap.add_argument(
        "--skip-gold-csv",
        action="store_true",
        help="Do not apply gold CSV",
    )
    args = ap.parse_args()

    db = args.db.resolve()
    sentiment_migrate.migrate(db)
    conn = sqlite3.connect(str(db))
    try:
        n = import_jsonl_comments(conn, args.jsonl.resolve())
        conn.commit()
        print(f"Imported {n} comments from {args.jsonl}")
        if (
            not args.skip_gold_csv
            and args.gold_csv
            and args.gold_csv.is_file()
        ):
            ng = apply_gold_labels_csv(conn, args.gold_csv.resolve())
            conn.commit()
            print(f"Applied {ng} gold labels from {args.gold_csv}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
