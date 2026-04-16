"""
HLTV match page + forum thread parsing and persistence.

Respect https://www.hltv.org/robots.txt: /forums/* is disallowed for crawlers.
By default we do not fetch forum URLs; use --fetch-forum only if you have
explicit permission or are using offline HTML snapshots.

See docs/HLTV_SENTIMENT_COLLECTION.md.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HLTV_ORIGIN = "https://www.hltv.org"
DEFAULT_UA = (
    "SteamApiSentimentResearch/1.0 (+https://github.com/local; academic research; "
    "respectful rate limits)"
)

CLOUDFLARE_MARKERS = (
    "cf-chl",
    "challenges.cloudflare.com",
    "Just a moment",
    "Enable JavaScript and cookies",
    "Checking your browser",
)

ESTIMATED_MAP_MINUTES = 50
ESTIMATED_MATCH_OVERHEAD_MINUTES = 10


@dataclass
class MatchMeta:
    match_id: int
    title: Optional[str] = None
    team1_name: Optional[str] = None
    team2_name: Optional[str] = None
    event_name: Optional[str] = None
    match_date_unix: Optional[int] = None
    match_start_unix: Optional[int] = None
    match_end_unix: Optional[int] = None
    status_hint: Optional[str] = None
    score_summary: Optional[str] = None
    forum_thread_url: Optional[str] = None
    source_match_url: Optional[str] = None


@dataclass
class ParsedComment:
    comment_id: str
    raw_text: str
    posted_at_unix: Optional[int] = None
    parent_id: Optional[str] = None
    score_context: Optional[str] = None
    gold_label: Optional[int] = None  # 0 neg, 1 neu, 2 pos; optional on import


def build_match_url(match_id: int) -> str:
    """HLTV accepts a random slug after the numeric id (see gigobyte/HLTV)."""
    slug = uuid.uuid4().hex
    return f"{HLTV_ORIGIN}/matches/{match_id}/{slug}"


def looks_like_cloudflare_block(html: str) -> bool:
    lower = html[:8000].lower()
    return any(m.lower() in lower for m in CLOUDFLARE_MARKERS)


def fetch_text(
    url: str,
    session: requests.Session,
    timeout: float = 30.0,
) -> str:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    text = r.text
    if looks_like_cloudflare_block(text):
        raise RuntimeError(
            "HLTV returned a Cloudflare challenge page; try saving HTML from a "
            "browser and --forum-html-file / --match-html-file, or use JSONL import."
        )
    return text


def _text(el) -> str:
    if el is None:
        return ""
    return " ".join(el.get_text(" ", strip=True).split())


def _unix_from_attr(raw: Any) -> Optional[int]:
    try:
        x = int(raw)
    except (TypeError, ValueError):
        return None
    return x // 1000 if x > 10**11 else x


def _count_played_maps(soup: BeautifulSoup) -> int:
    played = 0
    for holder in soup.select(".mapholder"):
        s1 = _text(holder.select_one(".results-left .results-team-score"))
        s2 = _text(holder.select_one(".results-right .results-team-score"))
        if re.fullmatch(r"\d+", s1) and re.fullmatch(r"\d+", s2):
            played += 1
    return played


def parse_match_page(html: str, match_id: int, source_url: str) -> MatchMeta:
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one(".timeAndEvent .text"))
    event_a = soup.select_one(".timeAndEvent .event a")
    event_name = _text(event_a) if event_a else None
    date_el = soup.select_one(".timeAndEvent .date")
    match_date_unix = None
    if date_el is not None and date_el.has_attr("data-unix"):
        match_date_unix = _unix_from_attr(date_el.get("data-unix"))

    match_start_unix = None
    match_end_unix = None
    start_el = soup.select_one(
        "[data-match-start-unix], .match-start [data-unix], .matchStart [data-unix], "
        ".timeAndEvent .time[data-unix], .timeAndEvent .date[data-unix]"
    )
    if start_el is not None:
        raw = (
            start_el.get("data-match-start-unix")
            or start_el.get("data-unix")
            or ""
        )
        match_start_unix = _unix_from_attr(raw)

    end_el = soup.select_one(
        "[data-match-end-unix], .match-end [data-unix], .matchEnd [data-unix]"
    )
    if end_el is not None:
        raw = end_el.get("data-match-end-unix") or end_el.get("data-unix") or ""
        match_end_unix = _unix_from_attr(raw)

    t1 = soup.select_one(".team1-gradient .teamName")
    t2 = soup.select_one(".team2-gradient .teamName")
    team1_name = _text(t1) if t1 else None
    team2_name = _text(t2) if t2 else None

    status_hint = None
    cd = soup.select_one(".countdown")
    if cd:
        status_hint = _text(cd)

    score_bits = []
    for holder in soup.select(".mapholder"):
        mname = _text(holder.select_one(".mapname"))
        s1 = holder.select_one(".results-left .results-team-score")
        s2 = holder.select_one(".results-right .results-team-score")
        if s1 and s2:
            score_bits.append(f"{mname}:{_text(s1)}-{_text(s2)}")
    score_summary = "; ".join(score_bits) if score_bits else None

    if match_start_unix is not None and match_end_unix is None:
        maps_played = _count_played_maps(soup)
        if maps_played > 0:
            est_minutes = (
                maps_played * ESTIMATED_MAP_MINUTES + ESTIMATED_MATCH_OVERHEAD_MINUTES
            )
            match_end_unix = match_start_unix + est_minutes * 60

    forum_thread_url = None
    match_comments = soup.select_one(".match-comments")
    if match_comments is not None:
        fo = match_comments.select_one(".forum[data-forum-thread-id]")
        if fo is not None and fo.has_attr("data-forum-thread-id"):
            try:
                tid = int(fo["data-forum-thread-id"])
                forum_thread_url = f"{HLTV_ORIGIN}/forums/threads/{tid}"
            except (TypeError, ValueError):
                pass
        if forum_thread_url is None:
            for a in match_comments.select('a[href*="/forums/threads/"]'):
                href = a.get("href") or ""
                if "/forums/threads/" in href:
                    forum_thread_url = urljoin(HLTV_ORIGIN, href)
                    break
    if forum_thread_url is None:
        for a in soup.select('a[href*="/forums/threads/"]'):
            href = a.get("href") or ""
            if "/forums/threads/" in href:
                forum_thread_url = urljoin(HLTV_ORIGIN, href)
                break

    return MatchMeta(
        match_id=match_id,
        title=title or None,
        team1_name=team1_name,
        team2_name=team2_name,
        event_name=event_name,
        match_date_unix=match_date_unix,
        match_start_unix=match_start_unix,
        match_end_unix=match_end_unix,
        status_hint=status_hint,
        score_summary=score_summary,
        forum_thread_url=forum_thread_url,
        source_match_url=source_url,
    )


def parse_forum_thread_html(html: str, match_id: int) -> list[ParsedComment]:
    """
    Parse forum thread HTML. HLTV markup changes over time; this tries several
    patterns and falls back to data-post-id containers.
    """
    soup = BeautifulSoup(html, "html.parser")
    posts: list[ParsedComment] = []

    # Strategy A: div.post with id post-123 (forum thread) or r123 (match page embed)
    for div in soup.select("div.post"):
        pid = (div.get("id") or "").strip()
        m = re.match(r"post-(\d+)$", pid) or re.match(r"r(\d+)$", pid)
        if not m:
            continue
        comment_id = m.group(1)
        unix = None
        for sel in ("span[data-unix]", ".post-date span[data-unix]", ".date[data-unix]"):
            du = div.select_one(sel)
            if du and du.has_attr("data-unix"):
                try:
                    raw = int(du["data-unix"])
                    unix = raw // 1000 if raw > 10**11 else raw
                except (TypeError, ValueError):
                    pass
                break
        body_el = div.select_one(
            ".forum-content, .forum-middle, .content, .post-body, .postbody"
        )
        raw_text = _text(body_el) if body_el else _text(div)
        if not raw_text:
            continue
        posts.append(
            ParsedComment(
                comment_id=comment_id,
                raw_text=raw_text,
                posted_at_unix=unix,
                parent_id=None,
                score_context=None,
            )
        )

    if posts:
        return posts

    # Strategy A2: post row + body cell (table-style / alternate skins)
    for tr in soup.select("tr.postRow, tr.forum-row, tr.postrow"):
        comment_id = None
        tid = tr.get("id") or ""
        m0 = re.match(r"post-(\d+)", tid)
        if m0:
            comment_id = m0.group(1)
        if not comment_id:
            pid_el = tr.select_one("[id^='post-'], [data-post-id]")
            if pid_el is not None:
                pid = pid_el.get("id") or ""
                m = re.match(r"post-(\d+)", pid)
                if m:
                    comment_id = m.group(1)
                elif pid_el.has_attr("data-post-id"):
                    try:
                        comment_id = str(int(pid_el["data-post-id"]))
                    except (TypeError, ValueError, KeyError):
                        pass
        if not comment_id:
            continue
        unix = None
        du = tr.select_one("[data-unix]")
        if du and du.has_attr("data-unix"):
            try:
                raw = int(du["data-unix"])
                unix = raw // 1000 if raw > 10**11 else raw
            except (TypeError, ValueError):
                pass
        body_el = tr.select_one(
            "td.postText, td.posttext, .post-msg, .postMessage, .forum-content"
        )
        raw_text = _text(body_el) if body_el else _text(tr)
        if not raw_text:
            continue
        posts.append(
            ParsedComment(
                comment_id=comment_id,
                raw_text=raw_text,
                posted_at_unix=unix,
                parent_id=None,
                score_context=None,
            )
        )

    if posts:
        return posts

    # Strategy B: data-post-id anywhere
    for el in soup.select("[data-post-id]"):
        try:
            comment_id = str(int(el["data-post-id"]))
        except (TypeError, ValueError, KeyError):
            continue
        unix = None
        du = el.select_one("[data-unix]")
        if du and du.has_attr("data-unix"):
            try:
                raw = int(du["data-unix"])
                unix = raw // 1000 if raw > 10**11 else raw
            except (TypeError, ValueError):
                pass
        raw_text = _text(el.select_one(".forum-content, .content") or el)
        if not raw_text:
            continue
        posts.append(
            ParsedComment(
                comment_id=comment_id,
                raw_text=raw_text,
                posted_at_unix=unix,
                parent_id=None,
                score_context=None,
            )
        )

    return posts


def _iso_from_unix(u: Optional[int]) -> Optional[str]:
    if u is None:
        return None
    try:
        return datetime.fromtimestamp(u, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return None


def upsert_match(conn: sqlite3.Connection, meta: MatchMeta) -> None:
    conn.execute(
        """
        INSERT INTO hltv_matches (
            match_id, title, team1_name, team2_name, event_name,
            match_date_unix, match_start_unix, match_end_unix,
            status_hint, score_summary, forum_thread_url,
            source_match_url, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
        ON CONFLICT(match_id) DO UPDATE SET
            title=excluded.title,
            team1_name=excluded.team1_name,
            team2_name=excluded.team2_name,
            event_name=excluded.event_name,
            match_date_unix=excluded.match_date_unix,
            match_start_unix=COALESCE(excluded.match_start_unix, hltv_matches.match_start_unix),
            match_end_unix=COALESCE(excluded.match_end_unix, hltv_matches.match_end_unix),
            status_hint=excluded.status_hint,
            score_summary=excluded.score_summary,
            forum_thread_url=excluded.forum_thread_url,
            source_match_url=excluded.source_match_url,
            updated_at=datetime('now')
        """,
        (
            meta.match_id,
            meta.title,
            meta.team1_name,
            meta.team2_name,
            meta.event_name,
            meta.match_date_unix,
            meta.match_start_unix,
            meta.match_end_unix,
            meta.status_hint,
            meta.score_summary,
            meta.forum_thread_url,
            meta.source_match_url,
        ),
    )


def upsert_comments(
    conn: sqlite3.Connection,
    match_id: int,
    comments: Iterable[ParsedComment],
    thread_url: Optional[str],
) -> int:
    n = 0
    for c in comments:
        conn.execute(
            """
            INSERT INTO hltv_comments (
                match_id, comment_id, parent_id, posted_at, posted_at_unix,
                raw_text, score_context, thread_url, gold_label
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(match_id, comment_id) DO UPDATE SET
                parent_id=excluded.parent_id,
                posted_at=excluded.posted_at,
                posted_at_unix=excluded.posted_at_unix,
                raw_text=excluded.raw_text,
                score_context=excluded.score_context,
                thread_url=excluded.thread_url,
                gold_label=COALESCE(excluded.gold_label, hltv_comments.gold_label)
            """,
            (
                match_id,
                c.comment_id,
                c.parent_id,
                _iso_from_unix(c.posted_at_unix),
                c.posted_at_unix,
                c.raw_text,
                c.score_context,
                thread_url,
                c.gold_label,
            ),
        )
        n += 1
    return n


def ensure_match_row(conn: sqlite3.Connection, match_id: int) -> None:
    """Minimal parent row for FK integrity (JSONL import)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO hltv_matches (match_id, title, updated_at)
        VALUES (?, ?, datetime('now'))
        """,
        (match_id, f"imported-match-{match_id}"),
    )


def import_jsonl_comments(
    conn: sqlite3.Connection,
    path: Path,
    default_match_id: Optional[int] = None,
) -> int:
    """
    Each line: JSON object with keys match_id, comment_id, raw_text,
    optional posted_at_unix, parent_id, score_context, thread_url.
    """
    total = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            mid = int(row.get("match_id", default_match_id or 0))
            if mid <= 0:
                raise ValueError("Each JSONL row needs match_id or pass default_match_id")
            ensure_match_row(conn, mid)
            cid = str(row["comment_id"])
            raw_text = str(row["raw_text"])
            gl = row.get("gold_label")
            if gl is not None and gl != "":
                gl = int(gl)
            else:
                gl = None
            pc = ParsedComment(
                comment_id=cid,
                raw_text=raw_text,
                posted_at_unix=row.get("posted_at_unix"),
                parent_id=row.get("parent_id"),
                score_context=row.get("score_context"),
                gold_label=gl,
            )
            upsert_comments(conn, mid, [pc], row.get("thread_url"))
            total += 1
    return total


def scrape_match_and_comments(
    match_id: int,
    db_path: Path,
    session: requests.Session,
    *,
    fetch_forum: bool = False,
    min_delay_s: float = 2.0,
    match_html: Optional[str] = None,
    forum_html: Optional[str] = None,
    skip_match_fetch: bool = False,
) -> dict[str, Any]:
    """
    Fetch match page, optionally forum thread, upsert into DB.
    When fetch_forum is False, only match metadata is stored unless forum_html is set.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = build_match_url(match_id)
    run_status = "ok"
    err = None
    n_comments = 0
    run_id: Optional[int] = None
    thread_url: Optional[str] = None
    html: Optional[str] = None

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO hltv_scrape_runs (match_id, status, source)
            VALUES (?, 'running', 'scrape_match_and_comments')
            """,
            (match_id,),
        )
        run_id = cur.lastrowid
        conn.commit()

        if match_html is not None:
            html = match_html
            meta = parse_match_page(html, match_id, url)
            upsert_match(conn, meta)
        elif skip_match_fetch:
            meta = MatchMeta(match_id=match_id, source_match_url=url)
            upsert_match(conn, meta)
        else:
            html = fetch_text(url, session)
            time.sleep(min_delay_s)
            meta = parse_match_page(html, match_id, url)
            upsert_match(conn, meta)
        conn.commit()

        thread_url = meta.forum_thread_url
        comments: list[ParsedComment] = []

        if forum_html is not None:
            comments.extend(parse_forum_thread_html(forum_html, match_id))
        elif fetch_forum and thread_url:
            logger.warning(
                "Fetching forum URL (robots.txt disallows /forums/ for automated agents): %s",
                thread_url,
            )
            fh = fetch_text(thread_url, session)
            time.sleep(min_delay_s)
            comments.extend(parse_forum_thread_html(fh, match_id))
        elif html is not None:
            # Match pages often embed the discussion (div.post id="r…"); no extra fetch.
            comments.extend(parse_forum_thread_html(html, match_id))

        if comments:
            n_comments = upsert_comments(conn, match_id, comments, thread_url)
        conn.commit()

        conn.execute(
            """
            UPDATE hltv_scrape_runs
            SET finished_at=datetime('now'), status=?, error_message=?, comments_ingested=?
            WHERE id=?
            """,
            (run_status, err, n_comments, run_id),
        )
        conn.commit()
        return {
            "match_id": match_id,
            "comments_ingested": n_comments,
            "forum_thread_url": thread_url,
            "run_id": run_id,
        }
    except Exception as e:
        err = str(e)
        conn.rollback()
        if run_id is not None:
            try:
                conn.execute(
                    """
                    UPDATE hltv_scrape_runs
                    SET finished_at=datetime('now'), status='error', error_message=?
                    WHERE id=?
                    """,
                    (err, run_id),
                )
                conn.commit()
            except sqlite3.Error:
                pass
        raise
    finally:
        conn.close()


def default_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": DEFAULT_UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
    )
    return s


def read_match_ids_from_csv(
    csv_path: Path,
    id_column: str = "match_id",
    limit: Optional[int] = None,
) -> list[int]:
    import csv

    url_pat = re.compile(r"/matches/(\d+)/")
    ids: list[int] = []
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return ids
        fields = {h.strip().lower(): h for h in reader.fieldnames}
        key = id_column.lower()
        if key not in fields:
            # try first column with 'match' in name
            alt = next(
                (h for h in reader.fieldnames if "match" in h.lower() and "id" in h.lower()),
                None,
            )
            if not alt:
                raise ValueError(
                    f"CSV missing column {id_column!r}; have {reader.fieldnames!r}"
                )
            col = alt
        else:
            col = fields[key]
        for row in reader:
            v = row.get(col)
            if v is None or str(v).strip() == "":
                continue
            s = str(v).strip()
            m = url_pat.search(s)
            if m:
                ids.append(int(m.group(1)))
            else:
                try:
                    ids.append(int(float(s)))
                except ValueError:
                    continue
            if limit is not None and len(ids) >= limit:
                break
    return ids
