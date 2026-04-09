# HLTV sentiment data collection

This project can store match metadata and forum-style comments in `data/hltv_sentiment.db` for NLP experiments (`nlp/` package and `scripts/train_sentiment_*.py`).

## Legal and robots.txt

- Review [HLTV Terms of Use](https://www.hltv.org/terms-of-use) before collecting data.
- [HLTV robots.txt](https://www.hltv.org/robots.txt) disallows crawling under `/forums/*` and many filtered `/matches?*` URLs. **Automated forum fetches are off by default** in `scripts/run_hltv_comment_collector.py`; use `--fetch-forum` only when you are permitted to do so.
- Do not redistribute scraped text if the site terms prohibit it.

## Cloudflare

Many unattended HTTP clients receive a Cloudflare challenge instead of real HTML. If live `requests` fail, save HTML from a normal browser session and pass:

- `--match-html-file path/to/match.html`
- `--forum-html-file path/to/thread.html`
- `--forum-html-only` with `--forum-html-file` skips the match HTTP request (minimal match row only).

## Commands

1. Create / migrate the DB:

   `python scripts/migrate_hltv_sentiment_db.py`

2. Collect (example):

   `python scripts/run_hltv_comment_collector.py --match-id 2378402`

3. Or import rows you already have:

   `python scripts/run_hltv_comment_collector.py --import-jsonl comments.jsonl`

   JSONL fields per line: `match_id`, `comment_id`, `raw_text`, optional `posted_at_unix`, `score_context`, `thread_url`.

4. Train baselines:

   `python scripts/train_sentiment_nb.py --ngram unigram`

   `python scripts/train_sentiment_lstm.py --epochs 10`

5. Evaluate:

   `python scripts/eval_sentiment.py --model-type nb`

## Rate limiting

The collector sleeps `--min-delay` seconds (default 2.5) between HTTP requests. Increase it if you see throttling or blocks.
