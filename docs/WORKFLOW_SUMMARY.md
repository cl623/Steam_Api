# Application Workflow Summary

## Overview

This document summarizes the complete workflow of the Steam Market application, including all the improvements we've made and how users interact with the system.

## Architecture

### Components

1. **Web Application** (`app/` package)
   - Flask-based web interface
   - Browse market listings
   - View price history charts
   - Manage cart
   - Configure settings

2. **Data Collector** (`collector/market_collector.py`)
   - Background script for continuous data collection
   - Multi-threaded (3 workers)
   - Rate-limited to respect Steam's limits
   - Incremental updates (12-hour intervals)

3. **Machine Learning** (`ml/price_predictor.py`)
   - Price prediction models
   - Uses collected data from database

4. **Database** (`data/market_data.db`)
   - SQLite database
   - Stores items, price history, ML features
   - Optimized with indexes for fast queries

## Complete User Workflow

### Initial Setup

```
1. Install Dependencies
   └─> pip install -r Requirements.txt

2. Get Steam Cookies
   └─> Browser: steamcommunity.com/market/pricehistory/...
   └─> DevTools (F12) → Network → Copy Cookie header

3. Test & Update Config
   └─> python scripts/test_cookies.py --cookie-string "..." --auto-update-config
   └─> Validates cookies
   └─> Tests price history access
   └─> Updates app/config.py automatically

4. Start Application
   └─> python run.py (web app)
   └─> python scripts/run_collector.py (data collector)
```

### Daily Usage

#### Web Application Flow

```
User opens browser
    ↓
http://127.0.0.1:5000
    ↓
Browse Market Listings
    ├─> Search items
    ├─> Filter by price
    └─> View item images
    ↓
Click on Item
    ↓
Price History Request
    ├─> Check database first (fast)
    ├─> If not in DB → Steam API (slower)
    └─> Display chart (last 3 months)
    ↓
Add to Cart (optional)
    ↓
View Cart
    └─> Full price history for all items
```

#### Data Collector Flow

```
Collector starts
    ↓
Initialize
    ├─> Load cookies from config
    ├─> Setup rate limiters
    ├─> Initialize database
    └─> Start worker threads (3)
    ↓
Main Loop (every 1 hour)
    ├─> Fetch market listings
    ├─> Add items to queue incrementally
    └─> Workers process queue in parallel
    ↓
Worker Threads (continuous)
    ├─> Get item from queue
    ├─> Check if data is fresh (< 12 hours)
    ├─> If stale → Fetch price history
    ├─> Store in database (batch insert)
    └─> Update last_updated timestamp
    ↓
Rate Limiting
    ├─> Listings: 1 req/min
    ├─> Price History: 7 req/min
    └─> Total: 8 req/min (safety limit)
```

## Cookie Management Workflow

### Cookie Priority Chain

```
Request for Price History
    ↓
get_steam_cookies() called
    ↓
Check Flask Session (highest priority)
    ├─> If cookies exist → Use them
    └─> Validate token audience
    ↓
If no session cookies
    ↓
Check Environment Variables
    ├─> STEAM_COOKIE_STRING
    ├─> STEAM_SESSIONID
    └─> STEAM_LOGIN_SECURE
    ↓
If no env vars
    ↓
Use DEFAULT_STEAM_COOKIES from app/config.py
    └─> Updated via test_cookies.py or import_cookies.py
```

### Cookie Update Workflow

```
User gets fresh cookies from browser
    ↓
Option 1: Test Script (Recommended)
    ├─> python scripts/test_cookies.py --cookie-string "..." --auto-update-config
    ├─> Validates cookies
    ├─> Tests price history access
    └─> Updates app/config.py automatically
    ↓
Option 2: Settings Page
    ├─> Go to /settings
    ├─> Paste cookie string
    ├─> Click "Parse Cookie String"
    ├─> Click "Save Settings"
    └─> Stores in Flask session (temporary)
    ↓
Option 3: Import Script
    └─> python scripts/import_cookies.py --cookie-string "..."
    └─> Updates app/config.py
```

## Data Flow

### Price History Request Flow

```
User clicks item in web app
    ↓
JavaScript requests /api/pricehistory
    ↓
Flask route: price_history()
    ├─> Get cookies (session → env → config)
    ├─> Validate token audience
    │   └─> Check if "web:community" in audience
    ├─> Check database first
    │   ├─> Query price_history table
    │   ├─> Filter last 90 days
    │   └─> If found → Return immediately
    ↓
If not in database
    ↓
Steam API Request
    ├─> Visit Steam homepage (establish session)
    ├─> Visit market listing page (get Akamai cookies)
    ├─> Request price history API
    └─> Parse response
    ↓
Return to User
    ├─> Display chart (last 3 months)
    └─> Optionally store in database (async)
```

### Data Collection Flow

```
Collector Main Thread
    ↓
Every 1 hour: Fetch Listings
    ├─> Rate limit: 1 req/min
    ├─> Fetch page 1, 2, 3... (incremental)
    ├─> Parse items
    └─> Add to queue as fetched (not all at once)
    ↓
Worker Threads (3 parallel)
    ↓
Worker gets item from queue
    ↓
Check if update needed
    ├─> Query last_updated from database
    ├─> Compare with update_interval (12 hours)
    └─> If fresh → Skip
    ↓
If stale or new item
    ↓
Fetch Price History
    ├─> Rate limit: 7 req/min (shared across workers)
    ├─> Visit Steam homepage
    ├─> Visit listing page
    ├─> Request price history API
    └─> Parse response
    ↓
Store in Database
    ├─> Batch insert (executemany)
    ├─> Validate data (no negative prices)
    ├─> Store normalized timestamps
    └─> Update last_updated
    ↓
Log Success
    └─> [SUCCESS] Processed item (X entries stored)
```

## Key Improvements Made

### 1. Cookie Management System
- **Cookie String Parser**: Paste full string, auto-extracts all cookies
- **Automatic Config Update**: Test and update in one command
- **Token Validation**: Checks audience before API calls
- **Multiple Sources**: Session, env vars, or config file

### 2. Data Collection Optimization
- **Incremental Updates**: Only updates stale data (12-hour default)
- **Separate Rate Limiters**: Listings (1/min) vs Price History (7/min)
- **Scheduled Listings**: Fixed 1-hour schedule, independent of queue
- **Incremental Queue Addition**: Items added as fetched, not all at once
- **Batch Database Writes**: 5-10x faster with executemany
- **SQLite Optimizations**: WAL mode, optimized cache, memory-mapped I/O

### 3. Web Application Enhancements
- **Database Integration**: Checks database first, faster responses
- **Token Validation**: Catches wrong audience tokens early
- **Better Error Messages**: Clear guidance for 400 errors
- **Cookie Source Logging**: Shows where cookies came from

### 4. Code Organization
- **Modular Structure**: Split into app/, collector/, ml/, scripts/
- **Flask Blueprint**: Better route organization
- **Centralized Config**: All constants in app/config.py
- **Utility Functions**: Reusable functions in app/utils.py

## Verification Checklist

### ✅ Setup Verification

- [ ] Dependencies installed
- [ ] Cookies configured and tested
- [ ] Config file updated (`app/config.py`)
- [ ] Database exists (`data/market_data.db`)

### ✅ Web App Verification

- [ ] App starts: `python run.py`
- [ ] Homepage loads: http://127.0.0.1:5000
- [ ] Items display in listings
- [ ] Price history chart loads when clicking item
- [ ] Settings page accessible
- [ ] Cookie test button works

### ✅ Collector Verification

- [ ] Collector starts: `python scripts/run_collector.py`
- [ ] Workers show activity: `[Worker-1] Processing...`
- [ ] Success messages: `[SUCCESS] Processed...`
- [ ] Database grows: Check `data/market_data.db`
- [ ] Logs created: `data/logs/market_collector.log`

### ✅ Cookie Verification

- [ ] Test passes: `python scripts/test_cookies.py --use-config`
- [ ] Token audience correct: `['web:community']`
- [ ] Price history accessible: 200+ entries retrieved
- [ ] Config updated: Check `app/config.py`

## Common Workflows

### Updating Cookies

```bash
# 1. Get fresh cookies from browser
# 2. Test and update automatically
python scripts/test_cookies.py --cookie-string "..." --auto-update-config

# 3. Restart Flask app to use new cookies
# 4. Clear Flask session cookies in Settings (if using session)
```

### Starting Fresh

```bash
# 1. Test cookies
python scripts/test_cookies.py --cookie-string "..." --auto-update-config

# 2. Start web app
python run.py

# 3. Start collector (separate terminal)
python scripts/run_collector.py

# 4. Verify both are working
# - Web app: Check price history loads
# - Collector: Check console for success messages
```

### Troubleshooting

```bash
# 1. Test cookies first
python scripts/test_cookies.py --use-config

# 2. If fails, get fresh cookies and update
python scripts/test_cookies.py --cookie-string "..." --auto-update-config

# 3. Check Flask session (if using Settings page)
# - Go to Settings
# - Clear cookies or update with fresh ones

# 4. Check logs
# - Collector: data/logs/market_collector.log
# - Web app: Console output
```

## Summary

The application provides a complete workflow for:
1. **Easy Cookie Setup**: Cookie string parser, automatic config update
2. **Reliable Data Collection**: Rate-limited, incremental, multi-threaded
3. **Fast Web Interface**: Database caching, optimized queries
4. **User-Friendly**: Clear error messages, validation, helpful guides

All components work together seamlessly:
- Web app uses cookies from config (updated via test script)
- Collector uses same cookies from config
- Database provides fast responses for web app
- Collector populates database in background

The system is production-ready with proper error handling, rate limiting, and user-friendly workflows.
