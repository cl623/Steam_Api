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


def test_parse_forum_thread_postrow_table():
    html = (_FIX / "hltv_forum_postrow.html").read_text(encoding="utf-8")
    posts = parse_forum_thread_html(html, 42)
    assert len(posts) == 2
    ids = {p.comment_id for p in posts}
    assert "88001" in ids and "88002" in ids


def test_parse_match_page_estimates_end_from_start_and_maps():
    html = (_FIX / "hltv_match_estimated_end.html").read_text(encoding="utf-8")
    meta = parse_match_page(html, 999002, "https://example/matches/999002/x")
    assert meta.match_start_unix == 1774780200
    # 3 maps * 50 min + 10 min overhead = 160 min
    assert meta.match_end_unix == 1774780200 + (160 * 60)


def test_parse_match_page_embedded_forum_r_id():
    html = (_FIX / "hltv_match_embedded_post.html").read_text(encoding="utf-8")
    meta = parse_match_page(html, 555, "https://example/matches/555/x")
    assert meta.forum_thread_url and "3120983" in meta.forum_thread_url
    posts = parse_forum_thread_html(html, 555)
    assert len(posts) == 1
    assert posts[0].comment_id == "12345"
    assert "Embedded match-page" in posts[0].raw_text
    assert posts[0].posted_at_unix == 1700000007
