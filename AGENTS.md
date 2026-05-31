# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

Single Python monorepo: **SteamScope** (Flask web app for CS2 Steam Community Market), optional **market collector** (`scripts/run_collector.py`), offline **ML** (`ml/`, `scripts/train_*.py`), and **HLTV sentiment NLP** (`nlp/`, `data/hltv_sentiment.db`). No Docker, no Node frontend, no configured linter.

### Dependencies

- Use **`requirements_python.txt`** for pip installs (includes Flask, PyTorch, pytest).
- Do **not** use `Requirements.txt` for pip — that file is a version changelog, not dependency pins.
- Project venv: **`.venv/`** at repo root. Activate with `source .venv/bin/activate` before running Python commands.
- On fresh Ubuntu images, `python3 -m venv` may require `python3.12-venv` (`sudo apt install python3.12-venv`) once per VM; this is not in the update script.

### Running services

| Service | Command | Notes |
|---------|---------|--------|
| Web app | `python run.py` | `http://127.0.0.1:5000`, debug mode, `0.0.0.0:5000` |
| Collector | `python scripts/run_collector.py` | Separate terminal; needs Steam cookies |
| Legacy app | `python app.py` | Older monolith; prefer `run.py` |

Use **tmux** for long-running dev servers (e.g. session `flask-dev-server`).

### Steam cookies

Price history and some market calls need valid Steam session cookies (`sessionid`, `steamLoginSecure`). Sources: `app/config.py` defaults, Settings UI (`/settings`), or `python scripts/test_cookies.py --cookie-string "..." --auto-update-config`. Without cookies, browse may work but price-history features fail.

### Database

- Market data: `data/market_data.db` (SQLite, auto-created). Run `python scripts/migrate_db.py` after clone if schema changes.
- Sentiment: `data/hltv_sentiment.db` — only for NLP track; CI tests use fixtures under `samples/`.

### Lint / test / build

- **Lint:** none configured in repo or CI.
- **Tests (CI subset):** see `.github/workflows/nlp-tests.yml` — five NLP pytest modules.
- **Full unit tests:** `python -m pytest tests/ -v --tb=short` — `tests/test_collector.py` has several tests that expect a `collector` pytest fixture and error under plain pytest; CI intentionally skips them.
- **Live integration:** `python tests/test_collector.py` or `python scripts/test_cookies.py --use-config` (hits Steam).
- **Build:** no compile step; training scripts write artifacts under `models/` (often gitignored).

### Hello-world (web)

1. `source .venv/bin/activate && python run.py`
2. Open `/`, search e.g. `Danger Zone Case`
3. Add an item to cart → `/cart` shows the line item

### Gotchas

- README quick start still says `pip install -r Requirements.txt` — use `requirements_python.txt` instead.
- `flask-sqlalchemy` is listed in requirements but the app uses raw `sqlite3`, not SQLAlchemy ORM.
- Cart UI may log a JS error updating `cartCount` on the market page; `globalCartCount` still updates and the server cart works.
