# Steam Market Web Application

A Flask-based web application for browsing Steam Community Market listings with price history tracking, cart functionality, and machine learning price predictions.

## Project Structure

```
Steam_Api/
├── app/                    # Main Flask application
│   ├── __init__.py        # Flask app factory
│   ├── config.py          # Configuration constants
│   ├── routes.py          # Flask routes/views
│   └── utils.py           # Utility functions
├── collector/             # Data collection package
│   ├── __init__.py
│   └── market_collector.py # Background data collector
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
├── templates/            # HTML templates (Flask)
│   ├── index.html
│   ├── cart.html
│   └── settings.html
├── static/               # Static files (CSS, JS)
│   └── css/
│       └── style.css
├── data/                 # Data files
│   ├── market_data.db       # SQLite database
│   └── logs/               # Log files
├── docs/                 # Documentation
│   ├── CODE_REVIEW.md
│   └── DATABASE_COLLECTION_REVIEW.md
├── run.py                # Main entry point
└── requirements.txt       # Python dependencies
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r Requirements.txt
```

### 2. Configure Steam Cookies (Required)

**Easiest Method - Cookie String:**
1. Get cookie string from browser:
   - Go to https://steamcommunity.com/market/pricehistory/?appid=730&market_hash_name=Danger%20Zone%20Case
   - Open DevTools (F12) → Network tab
   - Find `/market/pricehistory/` request → Headers → Request Headers
   - Copy the `Cookie:` header value

2. Test and update config:
```bash
python scripts/test_cookies.py --cookie-string "sessionid=...; steamLoginSecure=...; ..." --auto-update-config
```

**Alternative - Settings Page:**
- Start app: `python run.py`
- Go to http://127.0.0.1:5000/settings
- Paste cookie string → Parse → Save

### 3. Run the Application
```bash
# Web application
python run.py

# Data collector (in separate terminal)
python scripts/run_collector.py
```

**📖 For detailed setup instructions, see [docs/USER_GUIDE.md](docs/USER_GUIDE.md)**

## Features

- Browse Steam Community Market listings
- View price history charts (last 3 months on listings, full history in cart)
- Add items to cart
- Dark mode support
- Settings page for configuring Steam cookies and API keys
- Background data collection with rate limiting
- Machine learning price predictions
- Database caching for faster loading

## Configuration

- **Steam cookies**: Configure via Settings page, `test_cookies.py`, or `app/config.py`
- **Database path**: `data/market_data.db` (auto-created)
- **Logs**: `data/logs/market_collector.log`

## Documentation

- **[User Guide](docs/USER_GUIDE.md)** - Complete setup and usage instructions
- **[Cookie Setup Guide](docs/COOKIE_SETUP_GUIDE.md)** - Detailed cookie configuration
- **[Database Schema Review](docs/DATABASE_SCHEMA_ML_REVIEW.md)** - ML optimization details
- **[Data Collection Improvements](docs/DATA_COLLECTION_IMPROVEMENTS.md)** - Collector enhancements

## Key Features

### Cookie Management
- **Cookie String Parser**: Paste full cookie string, auto-extracts all cookies
- **Automatic Config Update**: Test and update config in one command
- **Token Validation**: Automatically checks token audience (`web:community` vs `web:store`)
- **Multiple Sources**: Flask session, environment variables, or config file

### Data Collection
- **Incremental Updates**: Only updates stale data (12-hour default)
- **Rate Limiting**: Respects Steam limits (8 req/min, 900 req/day)
- **Multi-threading**: 3 worker threads for parallel processing
- **Graceful Shutdown**: Clean shutdown with Ctrl+C

### Web Application
- **Database Integration**: Checks database first, faster responses
- **Price History Charts**: Last 3 months on listings, full history in cart
- **Dark Mode**: Toggle in Settings
- **Cart Management**: Add items, view full history

## Troubleshooting

**Price history not loading?**
1. Test cookies: `python scripts/test_cookies.py --use-config`
2. Check token audience (must be `web:community`)
3. Clear Flask session cookies in Settings
4. Verify account requirements (purchase, Steam Guard, market access)

**See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for complete troubleshooting guide.**
