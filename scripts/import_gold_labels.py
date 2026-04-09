#!/usr/bin/env python3
"""Apply gold labels from CSV to data/hltv_sentiment.db."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import migrate_hltv_sentiment_db as sentiment_migrate  # noqa: E402
from nlp.io_gold import apply_gold_labels_csv  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path, help="CSV with match_id, comment_id, label")
    ap.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "hltv_sentiment.db")
    args = ap.parse_args()

    db = args.db.resolve()
    sentiment_migrate.migrate(db)
    conn = sqlite3.connect(str(db))
    try:
        n = apply_gold_labels_csv(conn, args.csv.resolve())
        conn.commit()
        print(f"Updated {n} rows from {args.csv}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
