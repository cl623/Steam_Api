# Database Schema Review for Machine Learning Optimization

## Current Schema Analysis

### Current Tables

#### `items` Table
```sql
CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_hash_name TEXT NOT NULL,
    game_id TEXT NOT NULL,
    last_updated TIMESTAMP,
    UNIQUE(market_hash_name, game_id)
)
```

#### `price_history` Table
```sql
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,
    timestamp TIMESTAMP,  -- Stored as TEXT in Steam format: "Dec 06 2018 01: +0"
    price REAL,
    volume INTEGER,
    FOREIGN KEY (item_id) REFERENCES items (id),
    UNIQUE(item_id, timestamp, price, volume)
)
```

### Current Indexes
- `idx_items_game_hash` on `items(game_id, market_hash_name)`
- `idx_price_history_item_timestamp` on `price_history(item_id, timestamp)`
- `idx_price_history_timestamp` on `price_history(timestamp)`
- `idx_items_last_updated` on `items(last_updated)`

## ML Code Requirements Analysis

### Current ML Data Processing (`ml/price_predictor.py`)

The ML code performs the following operations:

1. **Data Loading**: Queries all items for a game, then price history for each item
2. **Timestamp Parsing**: Converts Steam timestamp format to pandas datetime (expensive)
3. **Feature Engineering**: Computes rolling windows in Python:
   - `price_ma7`: 7-day moving average of price
   - `price_ma30`: 30-day moving average of price
   - `price_std7`: 7-day standard deviation of price
   - `volume_ma7`: 7-day moving average of volume
4. **Target Creation**: Shifts price by `prediction_days` to create future price target

### Performance Issues Identified

1. **Timestamp Format**: TEXT format requires parsing on every query (slow)
2. **Python-based Feature Engineering**: Rolling averages computed in Python (slow for large datasets)
3. **No Pre-computed Features**: Features computed on-the-fly every time
4. **Inefficient Queries**: Multiple queries per item (N+1 problem)
5. **No Aggregated Statistics**: No pre-computed statistics for common ML features
6. **Missing Composite Indexes**: Could optimize for common query patterns

## Recommended Optimizations

### 1. Add Normalized Timestamp Column (HIGH PRIORITY)

**Problem**: Current timestamp is stored as TEXT in Steam format, requiring parsing every time.

**Solution**: Add a `timestamp_normalized` column with ISO format datetime.

```sql
ALTER TABLE price_history ADD COLUMN timestamp_normalized TIMESTAMP;

-- Create index for efficient date-based queries
CREATE INDEX IF NOT EXISTS idx_price_history_normalized 
ON price_history(item_id, timestamp_normalized);
```

**Benefits**:
- Faster datetime comparisons
- Enables efficient date range queries
- Works directly with pandas datetime
- Enables SQL-based feature engineering

### 2. Add Pre-computed Feature Columns (HIGH PRIORITY)

**Problem**: Rolling averages computed in Python are slow for large datasets.

**Solution**: Add columns for common ML features, updated incrementally.

```sql
ALTER TABLE price_history ADD COLUMN price_ma7 REAL;
ALTER TABLE price_history ADD COLUMN price_ma30 REAL;
ALTER TABLE price_history ADD COLUMN price_std7 REAL;
ALTER TABLE price_history ADD COLUMN volume_ma7 REAL;
ALTER TABLE price_history ADD COLUMN price_change_1d REAL;  -- Price change from previous day
ALTER TABLE price_history ADD COLUMN price_change_7d REAL;  -- Price change from 7 days ago
ALTER TABLE price_history ADD COLUMN volume_change_1d REAL;  -- Volume change from previous day
```

**Benefits**:
- Features computed once, used many times
- Faster ML data preparation
- Enables SQL-based feature selection
- Reduces Python processing time

### 3. Create Materialized View for ML Features (MEDIUM PRIORITY)

**Problem**: ML needs aggregated statistics across items and time periods.

**Solution**: Create a view with pre-computed features.

```sql
CREATE VIEW IF NOT EXISTS ml_features AS
SELECT 
    ph.item_id,
    ph.timestamp_normalized,
    ph.price,
    ph.volume,
    ph.price_ma7,
    ph.price_ma30,
    ph.price_std7,
    ph.volume_ma7,
    ph.price_change_1d,
    ph.price_change_7d,
    ph.volume_change_1d,
    -- Future price (target variable)
    LEAD(ph.price, 7) OVER (PARTITION BY ph.item_id ORDER BY ph.timestamp_normalized) AS future_price_7d,
    LEAD(ph.price, 30) OVER (PARTITION BY ph.item_id ORDER BY ph.timestamp_normalized) AS future_price_30d,
    -- Additional features
    i.game_id,
    i.market_hash_name,
    COUNT(*) OVER (PARTITION BY ph.item_id) AS total_data_points
FROM price_history ph
JOIN items i ON ph.item_id = i.id
WHERE ph.timestamp_normalized IS NOT NULL;
```

**Benefits**:
- Single query for ML data preparation
- Pre-computed window functions
- Easy to query for training data
- Can be indexed for performance

### 4. Add Composite Indexes for ML Queries (MEDIUM PRIORITY)

**Problem**: ML queries often filter by game_id, item_id, and date ranges.

**Solution**: Add composite indexes optimized for ML query patterns.

```sql
-- For ML data preparation queries
CREATE INDEX IF NOT EXISTS idx_ml_item_timestamp 
ON price_history(item_id, timestamp_normalized, price, volume);

-- For game-based queries
CREATE INDEX IF NOT EXISTS idx_ml_game_item 
ON items(game_id, id) INCLUDE (market_hash_name);
```

**Benefits**:
- Faster ML data loading
- Optimized for common query patterns
- Reduces query execution time

### 5. Add Statistics Table (LOW PRIORITY)

**Problem**: ML often needs item-level statistics (mean price, volatility, etc.).

**Solution**: Create a table with pre-computed item statistics.

```sql
CREATE TABLE IF NOT EXISTS item_statistics (
    item_id INTEGER PRIMARY KEY,
    mean_price REAL,
    std_price REAL,
    min_price REAL,
    max_price REAL,
    mean_volume REAL,
    price_volatility REAL,  -- Coefficient of variation
    trend_7d REAL,          -- 7-day price trend
    trend_30d REAL,         -- 30-day price trend
    last_updated TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items (id)
);

CREATE INDEX IF NOT EXISTS idx_item_stats_game 
ON item_statistics(item_id);
```

**Benefits**:
- Fast access to item-level features
- Enables feature engineering without full history
- Can be used for item similarity/clustering
- Reduces query complexity

### 6. Add Partitioning/Sharding Strategy (FUTURE)

**Problem**: As data grows, queries become slower.

**Solution**: Consider partitioning by date or game_id for very large datasets.

**Note**: SQLite doesn't support native partitioning, but we could:
- Use separate tables per game_id
- Use separate databases per time period
- Implement application-level partitioning

## Implementation Priority

### Phase 1: Critical Optimizations (Do First)
1. ✅ Add `timestamp_normalized` column
2. ✅ Add indexes for normalized timestamp
3. ✅ Create migration script to populate normalized timestamps

### Phase 2: Feature Engineering (Do Second)
1. ✅ Add pre-computed feature columns
2. ✅ Create function to compute and update features
3. ✅ Update collector to compute features on insert

### Phase 3: ML-Specific Optimizations (Do Third)
1. ✅ Create ML features view
2. ✅ Add composite indexes
3. ✅ Create item statistics table

### Phase 4: Advanced Features (Future)
1. ⏳ Consider partitioning strategy
2. ⏳ Add more advanced features (momentum, RSI, etc.)
3. ⏳ Implement feature versioning

## Migration Strategy

1. **Backward Compatible**: All changes should be additive (ALTER TABLE ADD COLUMN)
2. **Gradual Migration**: Populate new columns incrementally
3. **Dual Write**: Write to both old and new columns during transition
4. **Validation**: Verify data consistency after migration

## Expected Performance Improvements

- **Data Loading**: 5-10x faster with normalized timestamps and pre-computed features
- **Feature Engineering**: 10-20x faster with SQL-based features vs Python
- **ML Training**: 2-3x faster overall data preparation
- **Query Performance**: 3-5x faster with optimized indexes

## Code Changes Required

1. **Collector**: Update to compute and store normalized timestamps and features
2. **ML Predictor**: Update to use pre-computed features from database
3. **Migration Script**: Create script to backfill normalized timestamps and features
