# Database Collection Algorithm Review

## Overview
The `market_history_collector.py` implements a background data collection system for storing Steam market item data and price history in SQLite. This review analyzes the current implementation and identifies areas for improvement.

## Current Architecture

### Database Schema
```sql
-- Items table
CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT NOT NULL,
    game_id TEXT NOT NULL,
    last_updated TIMESTAMP,
    UNIQUE(market_hash_name, game_id)
)

-- Price history table
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,
    timestamp TIMESTAMP,
    price REAL,
    volume INTEGER,
    FOREIGN KEY (item_id) REFERENCES items (id),
    UNIQUE(item_id, timestamp, price, volume)
)
```

### Collection Flow
1. **Initialization**: Loads existing items from database
2. **Market Listings Fetch**: Fetches all market listings for each game (pagination)
3. **Queue System**: Adds items to priority queue (NEW items prioritized over OLD)
4. **Worker Threads**: Multiple workers process queue items
5. **Price History Fetch**: Each worker fetches price history for queued items
6. **Database Storage**: Stores items and price history with duplicate prevention

## Strengths

1. **Rate Limiting**: Implements rolling window rate limiting (10/min, 1000/day per game)
2. **Threading**: Uses worker threads for parallel processing
3. **Priority Queue**: Prioritizes new items over existing ones
4. **Error Handling**: Has retry logic and exponential backoff
5. **Duplicate Prevention**: Uses UNIQUE constraints to prevent duplicate entries
6. **Dynamic Sleep**: Adjusts sleep times based on rate limit status

## Critical Issues

### 1. **Price History Fetching Method (CRITICAL)**
**Problem**: The `fetch_price_history()` method uses simple GET requests without:
- Visiting the listing page first (required for Akamai cookies)
- Browser-like headers (Accept: text/html instead of application/json)
- Session management for cookie persistence

**Impact**: This will likely fail due to Steam's bot management, similar to the issue we fixed in `app.py`.

**Solution**: Update `fetch_price_history()` to match the working implementation in `app.py`:
```python
def fetch_price_history(self, game_id, market_hash_name):
    # Use requests.Session() for cookie persistence
    http_session = requests.Session()
    
    # Set cookies
    http_session.cookies.set('sessionid', self.steam_cookies['sessionid'], 
                           domain='steamcommunity.com', path='/')
    http_session.cookies.set('steamLoginSecure', self.steam_cookies['steamLoginSecure'],
                           domain='steamcommunity.com', path='/')
    
    # CRITICAL: Visit listing page first to get Akamai cookies
    from urllib.parse import quote
    listing_url = f'https://steamcommunity.com/market/listings/{game_id}/{quote(market_hash_name)}'
    listing_response = http_session.get(listing_url, headers=listing_headers, timeout=10)
    
    # Then fetch price history with browser-like headers
    api_headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,...',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        # ... (match app.py implementation)
    }
    response = http_session.get(url, params=params, headers=api_headers, timeout=10)
```

### 2. **No Integration with Flask App**
**Problem**: The collector runs as a standalone script. The Flask app doesn't:
- Query the database for cached price history
- Use database data to reduce API calls
- Have an endpoint to trigger collection

**Solution**: 
- Add database query functions to `app.py`
- Modify `/api/pricehistory` to check database first
- Add admin endpoint to trigger collection

### 3. **Inefficient Price History Updates**
**Problem**: The collector fetches ALL price history every time, even if only recent data is needed.

**Solution**: 
- Check `last_updated` timestamp in items table
- Only fetch price history if data is older than X hours
- Implement incremental updates

### 4. **Missing Indexes**
**Problem**: No database indexes on frequently queried columns.

**Solution**: Add indexes:
```sql
CREATE INDEX idx_items_game_hash ON items(game_id, market_hash_name);
CREATE INDEX idx_price_history_item_timestamp ON price_history(item_id, timestamp);
CREATE INDEX idx_price_history_timestamp ON price_history(timestamp);
```

### 5. **No Data Retention Policy**
**Problem**: Price history accumulates indefinitely, potentially causing:
- Large database size
- Slow queries
- Storage issues

**Solution**: Implement data retention:
- Keep full history for last 90 days
- Aggregate older data (daily/weekly averages)
- Archive or delete data older than 1 year

## Recommendations for Improvement

### 1. **Database Query Integration**
Add functions to `app.py` to query cached data:

```python
def get_price_history_from_db(market_hash_name, game_id, days=90):
    """Get price history from database for faster loading"""
    try:
        import sqlite3
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect('market_data.db') as conn:
            cursor = conn.cursor()
            # Get item_id
            cursor.execute('SELECT id FROM items WHERE market_hash_name = ? AND game_id = ?',
                         (market_hash_name, game_id))
            item_row = cursor.fetchone()
            if not item_row:
                return None
            
            # Get price history
            cursor.execute('''
                SELECT timestamp, price, volume 
                FROM price_history 
                WHERE item_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            ''', (item_row[0], cutoff_date))
            
            return [list(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"Error querying database: {e}")
        return None
```

### 2. **Update Price History Endpoint**
Modify `/api/pricehistory` to check database first:

```python
@app.route('/api/pricehistory')
def price_history():
    appid = request.args.get('appid')
    market_hash_name = request.args.get('market_hash_name')
    
    # Try database first
    db_data = get_price_history_from_db(market_hash_name, appid)
    if db_data:
        return jsonify({'prices': db_data, 'source': 'database'})
    
    # Fall back to API if no database data
    # ... existing API code ...
```

### 3. **Fix Collector's Price History Fetching**
Update `market_history_collector.py` to use the same working method as `app.py`.

### 4. **Add Collection Status Endpoint**
```python
@app.route('/api/collection-status')
def collection_status():
    """Get status of data collection"""
    try:
        import sqlite3
        with sqlite3.connect('market_data.db') as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM items')
            item_count = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM price_history')
            price_count = cursor.fetchone()[0]
            cursor.execute('SELECT MAX(last_updated) FROM items')
            last_update = cursor.fetchone()[0]
            
        return jsonify({
            'items_count': item_count,
            'price_history_count': price_count,
            'last_update': last_update
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### 5. **Add Database Maintenance**
```python
def cleanup_old_data(days_to_keep=365):
    """Remove price history older than specified days"""
    from datetime import datetime, timedelta
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    
    with sqlite3.connect('market_data.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM price_history 
            WHERE timestamp < ?
        ''', (cutoff_date,))
        conn.commit()
        return cursor.rowcount
```

## Performance Optimizations

1. **Batch Inserts**: Use `executemany()` for bulk inserts
2. **Connection Pooling**: Reuse database connections
3. **Async Processing**: Consider async/await for I/O operations
4. **Caching**: Cache frequently accessed items in memory

## Machine Learning Considerations

The current structure supports ML but could be enhanced:

1. **Feature Engineering Table**: Pre-compute features (moving averages, volatility, etc.)
2. **Prediction Storage**: Store model predictions for comparison
3. **Training Data Export**: Easy export to CSV/Parquet for ML pipelines

## Summary

The collection algorithm has a solid foundation but needs:
1. **URGENT**: Fix price history fetching to match working app.py implementation
2. **HIGH**: Integrate database queries into Flask app for faster loading
3. **MEDIUM**: Add database indexes and data retention policies
4. **LOW**: Add collection status and maintenance endpoints
