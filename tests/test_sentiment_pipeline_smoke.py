"""End-to-end smoke: migrate DB, NB train, LSTM train, eval (tiny data)."""

import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _seed_db(path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    import migrate_hltv_sentiment_db as m  # noqa: E402

    m.migrate(path)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT OR REPLACE INTO hltv_matches (match_id, title, team1_name, team2_name) "
        "VALUES (1, 't', 'A', 'B')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO hltv_matches (match_id, title, team1_name, team2_name) "
        "VALUES (2, 't', 'C', 'D')"
    )
    rows = [
        (1, "0", "insane clutch", 100, "14-12"),
        (1, "1", "nice try wp", 200, "14-14"),
        (1, "2", "terrible throw", 300, "14-16"),
        (2, "3", "love this team", 400, "10-10"),
        (2, "4", "disband trash", 500, "10-13"),
    ]
    for mid, cid, txt, ts, sc in rows:
        conn.execute(
            "INSERT OR REPLACE INTO hltv_comments (match_id, comment_id, raw_text, "
            "posted_at_unix, score_context) VALUES (?,?,?,?,?)",
            (mid, cid, txt, ts, sc),
        )
    conn.commit()
    conn.close()


def test_nb_lstm_eval_smoke(tmp_path):
    db = tmp_path / "h.db"
    _seed_db(db)
    out_nb = tmp_path / "nbout"
    out_lstm = tmp_path / "lstmout"
    ev = tmp_path / "ev"
    py = sys.executable
    r = subprocess.run(
        [
            py,
            str(ROOT / "scripts" / "train_sentiment_nb.py"),
            "--db",
            str(db),
            "--split-mode",
            "by_match",
            "--save-dir",
            str(out_nb),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    r2 = subprocess.run(
        [
            py,
            str(ROOT / "scripts" / "train_sentiment_lstm.py"),
            "--db",
            str(db),
            "--epochs",
            "2",
            "--batch-size",
            "2",
            "--save-dir",
            str(out_lstm),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    r3 = subprocess.run(
        [
            py,
            str(ROOT / "scripts" / "eval_sentiment.py"),
            "--db",
            str(db),
            "--model-type",
            "nb",
            "--checkpoint",
            str(out_nb / "nb_unigram.joblib"),
            "--out-dir",
            str(ev),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert r3.returncode == 0, r3.stderr + r3.stdout
    assert (ev / "confusion_nb_weak.png").is_file()
