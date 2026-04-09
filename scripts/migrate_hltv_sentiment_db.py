#!/usr/bin/env python3
"""
Create or upgrade the dedicated SQLite DB for HLTV sentiment / match-thread NLP.

Default path: data/hltv_sentiment.db (under project root).

Usage::

    python scripts/migrate_hltv_sentiment_db.py
    python scripts/migrate_hltv_sentiment_db.py --db path/to/custom.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def migrate(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS hltv_matches (
                match_id INTEGER PRIMARY KEY,
                title TEXT,
                team1_name TEXT,
                team2_name TEXT,
                event_name TEXT,
                match_date_unix INTEGER,
                status_hint TEXT,
                score_summary TEXT,
                forum_thread_url TEXT,
                source_match_url TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS hltv_comments (
                match_id INTEGER NOT NULL,
                comment_id TEXT NOT NULL,
                parent_id TEXT,
                posted_at TEXT,
                posted_at_unix INTEGER,
                raw_text TEXT NOT NULL,
                score_context TEXT,
                thread_url TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (match_id, comment_id),
                FOREIGN KEY (match_id) REFERENCES hltv_matches(match_id)
            );

            CREATE INDEX IF NOT EXISTS idx_hltv_comments_match_time
                ON hltv_comments(match_id, posted_at_unix);

            CREATE TABLE IF NOT EXISTS hltv_scrape_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                comments_ingested INTEGER DEFAULT 0,
                source TEXT,
                FOREIGN KEY (match_id) REFERENCES hltv_matches(match_id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )

    p = argparse.ArgumentParser(description="Migrate hltv_sentiment SQLite schema.")
    p.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "hltv_sentiment.db",
        help="Path to SQLite file",
    )
    args = p.parse_args()
    migrate(args.db.resolve())
    print(f"OK: schema ready at {args.db.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
