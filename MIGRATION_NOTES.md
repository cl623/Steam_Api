# Codebase Reorganization - Migration Notes

## Changes Made

The codebase has been reorganized into a standard Python project structure:

### New Directory Structure

```
Steam_Api/
├── app/                    # Main Flask application package
│   ├── __init__.py        # Flask app factory (create_app)
│   ├── config.py          # Configuration constants (GAMES, DEFAULT_STEAM_COOKIES, etc.)
│   ├── routes.py          # All Flask routes (moved from app.py)
│   └── utils.py           # Utility functions (get_steam_cookies, rate limiting, etc.)
├── collector/             # Data collection package
│   ├── __init__.py
│   └── market_collector.py # Background data collector (renamed from market_history_collector.py)
├── ml/                    # Machine learning package
│   ├── __init__.py
│   └── price_predictor.py # Price prediction models
├── tests/                 # Test suite
│   ├── __init__.py
│   └── test_collector.py
├── scripts/               # Utility scripts
│   ├── check_duplicates.py
│   ├── migrate_db.py
│   └── run_collector.py
├── templates/            # HTML templates (unchanged)
├── static/               # Static files (unchanged)
├── data/                 # Data files
│   ├── market_data.db       # SQLite database (moved from root)
│   └── logs/               # Log files (moved from root/logs)
├── docs/                 # Documentation
│   ├── CODE_REVIEW.md
│   └── DATABASE_COLLECTION_REVIEW.md
└── run.py                # Main entry point (NEW - replaces app.py)
```

### Key Changes

1. **app.py → app/ package**
   - Split into `app/__init__.py` (app factory), `app/routes.py` (routes), `app/config.py` (constants), `app/utils.py` (utilities)
   - Uses Flask Blueprint pattern for better organization

2. **Database Path Updates**
   - All database paths now default to `data/market_data.db`
   - Log files now go to `data/logs/`
   - Paths are resolved relative to project root

3. **Import Updates**
   - All imports updated to use new package structure
   - Scripts updated to add parent directory to sys.path

4. **Entry Point**
   - New `run.py` file replaces `app.py` as the main entry point
   - Old `app.py` can be removed (or kept for backward compatibility)

### Running the Application

**Before:**
```bash
python app.py
```

**After:**
```bash
python run.py
```

### Running the Collector

**Before:**
```bash
python market_history_collector.py
```

**After:**
```bash
python scripts/run_collector.py
```

### Running Tests

**Before:**
```bash
python test_collector.py
```

**After:**
```bash
python tests/test_collector.py
```

### Import Examples

**Before:**
```python
from market_history_collector import SteamMarketCollector
```

**After:**
```python
from collector.market_collector import SteamMarketCollector
```

**Before:**
```python
from app import GAMES, DEFAULT_STEAM_COOKIES
```

**After:**
```python
from app.config import GAMES, DEFAULT_STEAM_COOKIES
from app.utils import get_steam_cookies
```

### Files to Remove (Optional)

- `app.py` (replaced by `run.py` and `app/` package)
- Old log files in root directory (moved to `data/logs/`)
- Old database files in root (moved to `data/`)

### Backward Compatibility

The old `app.py` file can be kept temporarily for backward compatibility, but all new development should use the new structure.
