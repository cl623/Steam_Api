#!/usr/bin/env python3
"""
Collect HLTV match metadata and (optionally) forum comments into data/hltv_sentiment.db.

Examples::

    python scripts/migrate_hltv_sentiment_db.py
    python scripts/run_hltv_comment_collector.py --match-id 2378402

    # Offline: save match + forum HTML from browser, then:
    python scripts/run_hltv_comment_collector.py --match-id 2378402 \\
        --match-html-file saved_match.html --forum-html-file saved_thread.html

    python scripts/run_hltv_comment_collector.py --from-csv data/hltv_match_resultscs2.csv \\
        --csv-match-column match_url --limit 5

    python scripts/run_hltv_comment_collector.py --import-jsonl comments.jsonl
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from collector.hltv_comments import (  # noqa: E402
    default_session,
    import_jsonl_comments,
    read_match_ids_from_csv,
    scrape_match_and_comments,
)
import sqlite3  # noqa: E402

import migrate_hltv_sentiment_db as sentiment_migrate  # noqa: E402


def _match_ids_from_csv(args: argparse.Namespace) -> list[int]:
    p = Path(args.from_csv)
    if not p.is_file():
        raise FileNotFoundError(p)
    col = args.csv_match_column
    if col:
        return read_match_ids_from_csv(p, id_column=col, limit=args.limit)
    # try numeric column then URL scraping
    try:
        return read_match_ids_from_csv(
            p, id_column="match_id", limit=args.limit
        )
    except ValueError:
        pass
    import csv
    import re

    ids: list[int] = []
    with p.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return ids
        # prefer column containing match url
        url_col = next(
            (
                h
                for h in reader.fieldnames
                if "match" in h.lower() and "url" in h.lower()
            ),
            None,
        )
        if url_col is None:
            url_col = next(
                (h for h in reader.fieldnames if "url" in h.lower()), None
            )
        if url_col is None:
            raise ValueError(
                "Could not infer match id column; set --csv-match-column "
                f"to a column of ids or URLs. Headers: {reader.fieldnames!r}"
            )
        pat = re.compile(r"/matches/(\d+)/")
        for row in reader:
            cell = row.get(url_col) or ""
            m = pat.search(cell)
            if m:
                ids.append(int(m.group(1)))
            if args.limit is not None and len(ids) >= args.limit:
                break
    return ids


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser(description="HLTV comment / match metadata collector")
    ap.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "hltv_sentiment.db",
    )
    ap.add_argument("--match-id", type=int, action="append", dest="match_ids")
    ap.add_argument("--from-csv", type=Path, default=None)
    ap.add_argument(
        "--csv-match-column",
        type=str,
        default="",
        help="CSV column with numeric match_id (or leave empty for URL heuristic)",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--fetch-forum",
        action="store_true",
        help="HTTP-fetch forum thread (robots.txt disallows /forums/*; use only if allowed)",
    )
    ap.add_argument(
        "--min-delay",
        type=float,
        default=2.5,
        help="Seconds between HTTP requests",
    )
    ap.add_argument("--match-html-file", type=Path, default=None)
    ap.add_argument("--forum-html-file", type=Path, default=None)
    ap.add_argument(
        "--forum-html-only",
        action="store_true",
        help="Do not fetch match page; use minimal match row (use with --forum-html-file)",
    )
    ap.add_argument("--import-jsonl", type=Path, default=None)
    ap.add_argument(
        "--default-match-id",
        type=int,
        default=None,
        help="For JSONL rows missing match_id",
    )
    args = ap.parse_args()

    db_path = args.db.resolve()
    sentiment_migrate.migrate(db_path)
    if args.import_jsonl:
        conn = sqlite3.connect(str(db_path))
        try:
            n = import_jsonl_comments(
                conn, args.import_jsonl.resolve(), args.default_match_id
            )
            conn.commit()
        finally:
            conn.close()
        print(f"Imported {n} comments from {args.import_jsonl}")
        return 0

    match_ids: list[int] = list(args.match_ids or [])
    if args.from_csv:
        match_ids.extend(_match_ids_from_csv(args))
    if not match_ids:
        ap.error("Provide --match-id, --from-csv, or --import-jsonl")

    session = default_session()
    match_html = (
        args.match_html_file.read_text(encoding="utf-8", errors="replace")
        if args.match_html_file
        else None
    )
    forum_html = (
        args.forum_html_file.read_text(encoding="utf-8", errors="replace")
        if args.forum_html_file
        else None
    )

    for mid in match_ids:
        out = scrape_match_and_comments(
            mid,
            db_path,
            session,
            fetch_forum=args.fetch_forum,
            min_delay_s=args.min_delay,
            match_html=match_html,
            forum_html=forum_html,
            skip_match_fetch=args.forum_html_only,
        )
        print(out)
        # only reuse same HTML for first match
        match_html = None
        forum_html = None

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
