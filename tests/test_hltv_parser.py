from pathlib import Path

from collector.hltv_comments import parse_forum_thread_html, parse_match_page

_FIX = Path(__file__).resolve().parent / "fixtures"


def test_parse_match_page_minimal():
    html = (_FIX / "hltv_match_minimal.html").read_text(encoding="utf-8")
    meta = parse_match_page(html, 999001, "https://example/matches/999001/x")
    assert meta.match_id == 999001
    assert meta.team1_name == "Alpha"
    assert meta.team2_name == "Beta"
    assert meta.event_name == "Test Event"
    assert meta.score_summary and "Nuke" in meta.score_summary
    assert meta.forum_thread_url and "424242" in meta.forum_thread_url


def test_parse_forum_thread_minimal():
    html = (_FIX / "hltv_forum_minimal.html").read_text(encoding="utf-8")
    posts = parse_forum_thread_html(html, 999001)
    assert len(posts) == 2
    ids = {p.comment_id for p in posts}
    assert "1001" in ids and "1002" in ids
    assert "clutch" in posts[0].raw_text.lower() or "clutch" in posts[1].raw_text.lower()
