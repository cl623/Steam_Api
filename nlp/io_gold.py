"""Apply hand labels from CSV to hltv_comments.gold_label."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from nlp.gold_labels import parse_gold_label_cell


def apply_gold_labels_csv(conn: sqlite3.Connection, csv_path: Path) -> int:
    """
    CSV columns: match_id, comment_id, label (neg/neu/pos or 0/1/2).
    Returns number of rows updated.
    """
    n = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mid = int(row["match_id"])
            cid = str(row["comment_id"]).strip()
            lab = parse_gold_label_cell(row["label"])
            cur = conn.execute(
                """
                UPDATE hltv_comments SET gold_label = ?
                WHERE match_id = ? AND comment_id = ?
                """,
                (lab, mid, cid),
            )
            n += cur.rowcount
    return n
