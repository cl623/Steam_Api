# Steam Market Data Collection & Web App - User Guide

## Overview

This application provides:
1. **Web Interface**: Browse Steam Community Market listings, view price history charts, and manage a cart
2. **Data Collector**: Background script that continuously collects market data for machine learning
3. **Machine Learning**: Price prediction models using collected data

## Quick Start Guide

### 1. Initial Setup

#### Prerequisites
- Python 3.7+
- Steam account with:
  - Purchase in the last year
  - Steam Guard enabled for 15+ days
  - Market access enabled

#### Installation
```bash
# Install dependencies
pip install -r Requirements.txt

# Or if using dependencies.txt
pip install -r dependencies.txt
```

### 2. Configure Steam Cookies (Required)

**Why?** Steam requires authentication cookies to access price history data.

#### Method 1: Cookie String (Easiest - Recommended)

1. **Get Cookie String:**
   - Open https://steamcommunity.com/market/pricehistory/?appid=730&market_hash_name=Danger%20Zone%20Case in your browser (while logged in)
   - Open Developer Tools (F12) → **Network** tab
   - Find the request to `/market/pricehistory/` (first/only request)
   - Click it → **Headers** tab → **Request Headers**
   - Copy the entire `Cookie:` header value

2. **Test and Update Config:**
   ```bash
   python scripts/test_cookies.py --cookie-string "sessionid=...; steamLoginSecure=...; ..." --auto-update-config
   ```
   
   This will:
   - Validate your cookies
   - Test price history access
   - Automatically update `app/config.py` if all tests pass

3. **Or Use Settings Page:**
   - Start the Flask app: `python run.py` or `python app.py`
   - Go to http://127.0.0.1:5000/settings
   - Paste cookie string in "Cookie String" field
   - Click "Parse Cookie String"
   - Click "Save Settings"
   - Click "Test Cookies" to verify

#### Method 2: Import Script

```bash
python scripts/import_cookies.py --cookie-string "sessionid=...; steamLoginSecure=...; ..."
```

### 3. Start the Application

#### Web Application
```bash
# Recommended (new structure)
python run.py

# Or (old structure, still works)
python app.py
```

The app will be available at: http://127.0.0.1:5000

#### Data Collector (Background)
```bash
# Run with defaults (3 workers, 12-hour update interval)
python scripts/run_collector.py

# Or with custom settings
python scripts/run_collector.py --workers 4 --update-interval 6
```

## User Workflow

### Web Application Usage

#### 1. Browse Market Listings
- Go to http://127.0.0.1:5000
- Select game (default: Counter-Strike 2)
- Browse items, search, filter by price
- View item images and current prices

#### 2. View Price History
- Click on any item to view its price history chart
- Chart shows last 3 months of data
- Full history available in cart

#### 3. Manage Cart
- Click "Add to Cart" on items
- View cart to see all selected items
- View full price history for all cart items
- Clear cart when done

#### 4. Settings
- **Steam Cookies**: Configure authentication cookies
  - Use cookie string (easiest) or individual cookies
  - Test cookies before saving
  - Cookies stored in Flask session (temporary) or config file (persistent)
- **Appearance**: Toggle dark mode
- **API Key**: Optional SteamApis.com key

### Data Collector Usage

#### Starting the Collector
```bash
python scripts/run_collector.py
```

#### What It Does
1. **Discovers Items**: Fetches all market listings for CS2 (every hour)
2. **Collects Price History**: Worker threads fetch price history for each item
3. **Stores Data**: Saves to `data/market_data.db`
4. **Incremental Updates**: Only updates items older than 12 hours (configurable)
5. **Rate Limiting**: Respects Steam's rate limits (8 req/min, 900 req/day)

#### Monitoring
- Watch console output for progress
- Check logs: `data/logs/market_collector.log`
- Monitor database: `data/market_data.db`

#### Stopping the Collector
- Press `Ctrl+C` for graceful shutdown
- Workers finish current operations
- Queue is processed (up to 60s timeout)

## Cookie Management System

### Cookie Priority Order

The app checks cookies in this order:
1. **Flask Session** (from Settings page) - Highest priority
2. **Environment Variables** (`STEAM_COOKIE_STRING`, etc.)
3. **Config File** (`app/config.py` - `DEFAULT_STEAM_COOKIES`)

### Cookie Sources

#### Flask Session (Temporary)
- Set via Settings page
- Stored in browser session
- Lost when browser closes
- Best for: Quick testing, temporary use

#### Config File (Persistent)
- Updated via `test_cookies.py --auto-update-config`
- Or manually edit `app/config.py`
- Persists across restarts
- Best for: Production, collector script

### Cookie Validation

The app automatically validates cookies:
- **Token Audience Check**: Ensures token has `"web:community"` audience (not `"web:store"`)
- **Format Validation**: Checks cookie format
- **Access Test**: Tests actual price history access

**Common Issues:**
- ❌ Wrong audience: Cookies from `store.steampowered.com` won't work
- ✅ Correct: Cookies from `steamcommunity.com` work
- ❌ Expired cookies: Update when you get 400/401 errors
- ✅ Fresh cookies: Get from Network tab in browser DevTools

## Verification & Testing

### 1. Test Cookies
```bash
# Test with cookie string
python scripts/test_cookies.py --cookie-string "..." --auto-update-config

# Test with config file
python scripts/test_cookies.py --use-config

# Test and prompt to update
python scripts/test_cookies.py --cookie-string "..." --update-config
```

### 2. Verify Web App
1. Start Flask app: `python run.py`
2. Go to http://127.0.0.1:5000
3. Click on any item
4. Check if price history chart loads
5. If you see data → ✅ Working!
6. If you see errors → Check cookies in Settings

### 3. Verify Collector
1. Start collector: `python scripts/run_collector.py`
2. Watch console for:
   - `[Worker-1] [SUCCESS] Successfully processed...`
   - `Retrieved X price history entries`
3. Check database: `data/market_data.db` should grow
4. Check logs: `data/logs/market_collector.log`

## Troubleshooting

### Price History Not Loading

**Symptoms:**
- Chart shows "No data available"
- 400 error in console
- Empty array `[]` response

**Solutions:**
1. **Check Cookie Source:**
   ```bash
   python scripts/test_cookies.py --use-config
   ```
   - If fails → Update cookies
   - If passes → Clear Flask session cookies in Settings

2. **Verify Token Audience:**
   - Cookies must be from `steamcommunity.com` (not `store.steampowered.com`)
   - Token must have `"aud": ["web:community"]`

3. **Check Account Requirements:**
   - Purchase in last year
   - Steam Guard enabled 15+ days
   - Market access enabled

4. **Clear Flask Session:**
   - Go to Settings page
   - Click "Reset to Defaults"
   - Or manually clear cookie fields
   - This forces app to use config file cookies

### Collector Not Working

**Symptoms:**
- No data being collected
- Workers showing errors
- Rate limit warnings

**Solutions:**
1. **Check Cookies:**
   ```bash
   python scripts/test_cookies.py --use-config
   ```

2. **Check Rate Limits:**
   - Watch for 429 errors
   - Collector automatically handles rate limits
   - May need to wait if rate limited

3. **Check Database:**
   - Verify `data/market_data.db` exists
   - Check file permissions
   - Ensure disk space available

4. **Check Logs:**
   - Review `data/logs/market_collector.log`
   - Look for error messages
   - Check worker status

### Cookies Expired

**Symptoms:**
- 401 Unauthorized errors
- 403 Forbidden errors
- Price history requests fail

**Solution:**
1. Get fresh cookies from browser
2. Test: `python scripts/test_cookies.py --cookie-string "..." --auto-update-config`
3. Update Settings page if using session cookies

## File Structure

```
Steam_Api/
├── app/                    # Flask application
│   ├── __init__.py        # App factory
│   ├── config.py          # Configuration (cookies, games, etc.)
│   ├── routes.py          # All Flask routes
│   └── utils.py           # Utility functions
├── collector/             # Data collection
│   └── market_collector.py
├── ml/                    # Machine learning
│   └── price_predictor.py
├── scripts/               # Utility scripts
│   ├── run_collector.py   # Start collector
│   ├── test_cookies.py    # Test/update cookies
│   └── import_cookies.py  # Import cookies to config
├── templates/            # HTML templates
├── static/               # CSS/JS files
├── data/                 # Database & logs
│   ├── market_data.db
│   └── logs/
├── run.py                # Main entry point (recommended)
└── app.py                # Legacy entry point (still works)
```

## Key Features

### 1. Cookie String Parser
- Paste full cookie string from browser
- Automatically extracts all cookies
- No manual field entry needed

### 2. Automatic Config Update
- Test cookies and update config in one command
- `--auto-update-config` flag for automation
- Validates before updating

### 3. Token Audience Validation
- Automatically checks token audience
- Warns if wrong audience (`web:store` vs `web:community`)
- Prevents wasted API calls

### 4. Incremental Data Collection
- Only updates stale data (12-hour default)
- Efficient use of rate limits
- Faster collection cycles

### 5. Database Integration
- Web app checks database first
- Faster responses
- Reduced API calls
- Automatic fallback to API

## Best Practices

1. **Cookie Management:**
   - Use cookie string method (easiest)
   - Test before using in production
   - Update when cookies expire
   - Use `--auto-update-config` for automation

2. **Data Collection:**
   - Run collector continuously
   - Monitor logs regularly
   - Adjust worker count based on rate limits
   - Use incremental updates (default 12 hours)

3. **Web App:**
   - Clear session cookies if config updated
   - Use Settings page for quick testing
   - Use config file for production

4. **Troubleshooting:**
   - Always test cookies first
   - Check token audience if 400 errors
   - Verify account requirements
   - Check logs for detailed errors

## Summary

**To get started:**
1. Install dependencies
2. Get cookies from browser (cookie string method)
3. Test and update: `python scripts/test_cookies.py --cookie-string "..." --auto-update-config`
4. Start web app: `python run.py`
5. Start collector: `python scripts/run_collector.py`

**To verify it's working:**
1. Web app: Browse items, check price history loads
2. Collector: Watch console for success messages
3. Database: Check `data/market_data.db` grows

**If issues:**
1. Test cookies: `python scripts/test_cookies.py --use-config`
2. Check token audience (must be `web:community`)
3. Clear Flask session cookies if using Settings page
4. Check account requirements (purchase, Steam Guard, market access)
