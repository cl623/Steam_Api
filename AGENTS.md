# AGENTS.md

## Cursor Cloud specific instructions

Single-product **Python / Flask** repo (SteamScope Steam Market web app). No Docker, no Node, no separate DB servers — only SQLite files under `data/`.

### Dependencies

- Use the project venv at `.venv` (create with `python3 -m venv .venv` if missing).
- Install from `requirements_python.txt` (CI source of truth), not legacy `Requirements.txt` / `dependencies.txt`.
- Activate for manual commands: `source .venv/bin/activate` or prefix with `.venv/bin/python` / `.venv/bin/pip`.

### Lint / test

- No project-wide linter configured in-repo.
- CI NLP tests (matches `.github/workflows/nlp-tests.yml`):

```bash
.venv/bin/python -m pytest tests/test_nlp_preprocess.py tests/test_hltv_parser.py \
  tests/test_velocity_lag.py tests/test_gold_labels.py \
  tests/test_sentiment_pipeline_smoke.py -v
```

### Run the web app (development)

```bash
.venv/bin/python run.py
```

- Listens on `http://127.0.0.1:5000` (`host=0.0.0.0` in `run.py`).
- Live market listings call **steamcommunity.com**; no local Steam service required.
- **Price history** and cookie validation need valid Steam cookies — see `docs/COOKIE_SETUP_GUIDE.md` and `/settings`, or `scripts/test_cookies.py`.

### Optional background services

| Service | Command | Notes |
|---------|---------|--------|
| Market data collector | `.venv/bin/python scripts/run_collector.py` | Fills `data/market_data.db`; separate long-running process |
| HLTV sentiment pipeline | migrate/import scripts in `docs/HLTV_SENTIMENT_COLLECTION.md` | Batch/offline; not needed for Flask or CI pytest |

### Gotchas

- Reinstalling deps does not restart a running Flask process — restart `run.py` after dependency changes.
- `tests/test_collector.py` is a manual live-integration script (Steam cookies + network), not part of CI pytest.
- Torch pulls large CUDA-related wheels on Linux; first `pip install` can take several minutes.
