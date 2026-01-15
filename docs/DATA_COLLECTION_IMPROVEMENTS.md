# Data Collection Process Improvements

## Comprehensive Analysis and Recommendations

### Current State Assessment

The collector is functional but has several areas for optimization and improvement.

---

## 1. Database Operations Optimization (HIGH PRIORITY)

### Current Issues
- **Individual commits per item**: Each price history entry commits separately
- **No batching**: Inserts are done one-by-one
- **Multiple connections**: New connection for each operation
- **No bulk operations**: Missing bulk insert capabilities

### Improvements

#### 1.1 Batch Database Writes
**Current**: Each price history entry commits individually
```python
# Current: 100 entries = 100 commits
for entry in price_data['prices']:
    cursor.execute('INSERT ...')
    conn.commit()  # Individual commit
```

**Improved**: Batch commits
```python
# Improved: 100 entries = 1 commit
batch_size = 100
for i, entry in enumerate(price_data['prices']):
    cursor.execute('INSERT ...')
    if (i + 1) % batch_size == 0:
        conn.commit()  # Batch commit
conn.commit()  # Final commit
```

**Benefits**:
- 10-50x faster database writes
- Reduced I/O overhead
- Better transaction management

#### 1.2 Use Executemany for Bulk Inserts
**Current**: Individual INSERT statements
**Improved**: Use `executemany()` for bulk inserts

```python
# Prepare all entries
entries = [(item_id, ts, price, vol, normalized_ts) for ...]
cursor.executemany('''
    INSERT OR IGNORE INTO price_history 
    (item_id, timestamp, timestamp_normalized, price, volume)
    VALUES (?, ?, ?, ?, ?)
''', entries)
conn.commit()
```

**Benefits**:
- 5-10x faster than individual inserts
- Single transaction
- Better error handling

#### 1.3 Connection Pooling/Reuse
**Current**: New connection for each operation
**Improved**: Reuse connections within worker threads

```python
# Per-worker connection (thread-local)
class WorkerConnection:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute('PRAGMA journal_mode=WAL')  # Better concurrency
    
    def close(self):
        self.conn.close()
```

**Benefits**:
- Reduced connection overhead
- Better concurrency with WAL mode
- Faster operations

---

## 2. Session Management Optimization (MEDIUM PRIORITY)

### Current Issues
- **New session per request**: Creates new `requests.Session()` for each price history fetch
- **No session reuse**: Sessions are discarded after use
- **Cookie overhead**: Re-establishes cookies every time

### Improvements

#### 2.1 Per-Worker Session Pool
**Current**: New session for each fetch
**Improved**: Reuse sessions per worker thread

```python
# Thread-local session storage
import threading
thread_local = threading.local()

def get_session():
    if not hasattr(thread_local, 'session'):
        thread_local.session = requests.Session()
        # Set cookies once
        thread_local.session.cookies.set('sessionid', ...)
    return thread_local.session
```

**Benefits**:
- Faster requests (no session setup overhead)
- Better cookie management
- Reduced memory allocation

#### 2.2 Session Health Checks
**Current**: No validation of session health
**Improved**: Validate session before use, recreate if needed

```python
def get_healthy_session():
    session = get_session()
    # Check if session is still valid (optional)
    # Recreate if needed
    return session
```

---

## 3. Error Handling & Resilience (HIGH PRIORITY)

### Current Issues
- **Limited retry logic**: Some errors not retried
- **Database errors**: Not all database errors are handled
- **Network failures**: Timeouts handled but could be better
- **No circuit breaker**: Continues retrying on persistent failures

### Improvements

#### 3.1 Comprehensive Retry Logic
**Current**: Basic retry for rate limits only
**Improved**: Retry for all transient errors

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError))
)
def fetch_price_history_with_retry(self, game_id, market_hash_name):
    # Fetch with automatic retry
    pass
```

#### 3.2 Circuit Breaker Pattern
**Current**: Continues retrying on persistent failures
**Improved**: Circuit breaker to stop retrying on persistent failures

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = 0
        self.state = 'closed'  # closed, open, half_open
    
    def call(self, func, *args, **kwargs):
        if self.state == 'open':
            if time.time() - self.last_failure_time > self.timeout:
                self.state = 'half_open'
            else:
                raise CircuitBreakerOpen()
        
        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise
```

#### 3.3 Database Error Handling
**Current**: Basic error logging
**Improved**: Comprehensive error handling with recovery

```python
def store_price_history(self, item_id, price_data):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Database operation
            with sqlite3.connect(self.db_path) as conn:
                # ... operations ...
                conn.commit()
            return
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))  # Backoff for locked DB
                continue
            raise
        except sqlite3.IntegrityError as e:
            # Duplicate entry - not an error, just log
            logging.debug(f"Duplicate entry (expected): {e}")
            return
```

---

## 4. Data Validation & Quality (MEDIUM PRIORITY)

### Current Issues
- **No data validation**: Accepts any price/volume values
- **No sanity checks**: Could store invalid data (negative prices, etc.)
- **No outlier detection**: Anomalous data stored as-is

### Improvements

#### 4.1 Data Validation
```python
def validate_price_data(self, price, volume, timestamp):
    """Validate price history data before storing"""
    # Price validation
    if price < 0:
        logging.warning(f"Invalid price: {price}")
        return False
    
    if price > 1000000:  # Sanity check (very high price)
        logging.warning(f"Suspiciously high price: {price}")
        return False
    
    # Volume validation
    if volume < 0:
        logging.warning(f"Invalid volume: {volume}")
        return False
    
    # Timestamp validation
    if not timestamp or len(timestamp) < 10:
        logging.warning(f"Invalid timestamp: {timestamp}")
        return False
    
    return True
```

#### 4.2 Outlier Detection
```python
def detect_outliers(self, prices):
    """Detect and flag outliers using statistical methods"""
    if len(prices) < 10:
        return []  # Not enough data
    
    import numpy as np
    mean = np.mean(prices)
    std = np.std(prices)
    
    outliers = []
    for i, price in enumerate(prices):
        z_score = abs((price - mean) / std) if std > 0 else 0
        if z_score > 3:  # 3 standard deviations
            outliers.append((i, price, z_score))
    
    return outliers
```

---

## 5. Performance Monitoring & Metrics (LOW PRIORITY)

### Current Issues
- **Limited metrics**: Only basic logging
- **No performance tracking**: Can't measure throughput
- **No health checks**: Can't detect if collector is stuck

### Improvements

#### 5.1 Metrics Collection
```python
class CollectorMetrics:
    def __init__(self):
        self.items_processed = 0
        self.items_failed = 0
        self.requests_made = 0
        self.rate_limit_hits = 0
        self.db_writes = 0
        self.start_time = time.time()
        self.lock = threading.Lock()
    
    def record_item_processed(self):
        with self.lock:
            self.items_processed += 1
    
    def get_stats(self):
        elapsed = time.time() - self.start_time
        return {
            'items_processed': self.items_processed,
            'items_per_hour': self.items_processed / (elapsed / 3600),
            'success_rate': self.items_processed / (self.items_processed + self.items_failed),
            'rate_limit_hits': self.rate_limit_hits,
        }
```

#### 5.2 Health Check Endpoint
```python
def health_check(self):
    """Check if collector is healthy"""
    checks = {
        'workers_running': self.get_active_workers(),
        'queue_size': self.item_queue.qsize(),
        'last_activity': self.get_last_activity_time(),
        'database_accessible': self.check_database(),
    }
    return all(checks.values()), checks
```

---

## 6. Queue Management (MEDIUM PRIORITY)

### Current Issues
- **No queue size limits**: Could grow unbounded
- **No priority aging**: Old items stay at same priority
- **No duplicate detection**: Same item could be queued multiple times

### Improvements

#### 6.1 Queue Size Limits
```python
MAX_QUEUE_SIZE = 10000

def add_to_queue(self, game_id, market_hash_name, priority=None):
    if self.item_queue.qsize() >= MAX_QUEUE_SIZE:
        logging.warning("Queue full, dropping lowest priority items")
        # Remove some low-priority items
        self.trim_queue()
    
    # Add item
    self.item_queue.put((priority, (game_id, market_hash_name)))
```

#### 6.2 Duplicate Prevention
```python
self.queued_items = set()  # Track queued items

def add_to_queue(self, game_id, market_hash_name, priority=None):
    item_key = (game_id, market_hash_name)
    if item_key in self.queued_items:
        logging.debug(f"Item already in queue: {market_hash_name}")
        return
    
    self.queued_items.add(item_key)
    self.item_queue.put((priority, item_key))
    
    # Remove from set when processed
    def worker(self):
        # ... process item ...
        self.queued_items.discard(item_key)
```

---

## 7. Configuration & Flexibility (LOW PRIORITY)

### Current Issues
- **Hardcoded values**: Many parameters hardcoded
- **No configuration file**: Can't adjust without code changes
- **Limited customization**: Difficult to tune for different scenarios

### Improvements

#### 7.1 Configuration File
```python
# config.yaml
collector:
  num_workers: 3
  update_interval_hours: 12
  batch_size: 100
  max_queue_size: 10000
  rate_limit:
    requests_per_minute: 8
    requests_per_day: 900
  retry:
    max_attempts: 3
    backoff_multiplier: 2
```

#### 7.2 Environment Variables
```python
NUM_WORKERS = int(os.getenv('COLLECTOR_NUM_WORKERS', '3'))
UPDATE_INTERVAL = int(os.getenv('COLLECTOR_UPDATE_INTERVAL_HOURS', '12'))
BATCH_SIZE = int(os.getenv('COLLECTOR_BATCH_SIZE', '100'))
```

---

## 8. SQLite Optimizations (MEDIUM PRIORITY)

### Current Issues
- **No WAL mode**: Default journal mode
- **No PRAGMA optimizations**: Missing performance settings
- **Synchronous writes**: Could be optimized

### Improvements

#### 8.1 Enable WAL Mode
```python
def init_database(self):
    with sqlite3.connect(self.db_path) as conn:
        # Enable WAL mode for better concurrency
        conn.execute('PRAGMA journal_mode=WAL')
        # Optimize for bulk inserts
        conn.execute('PRAGMA synchronous=NORMAL')  # Faster than FULL
        conn.execute('PRAGMA cache_size=-64000')  # 64MB cache
        conn.execute('PRAGMA temp_store=MEMORY')
        # ... rest of init ...
```

**Benefits**:
- Better concurrent read/write performance
- Faster bulk operations
- Reduced lock contention

---

## Implementation Priority

### Phase 1: Critical Performance (Do First)
1. ✅ Batch database writes (10-50x improvement)
2. ✅ Use executemany for bulk inserts (5-10x improvement)
3. ✅ Enable SQLite WAL mode (2-3x improvement)
4. ✅ Comprehensive error handling

### Phase 2: Reliability (Do Second)
1. ✅ Circuit breaker pattern
2. ✅ Data validation
3. ✅ Queue management improvements
4. ✅ Session reuse

### Phase 3: Monitoring (Do Third)
1. ✅ Metrics collection
2. ✅ Health checks
3. ✅ Performance monitoring

### Phase 4: Configuration (Future)
1. ⏳ Configuration file
2. ⏳ Environment variables
3. ⏳ Dynamic tuning

---

## Expected Overall Improvements

| Optimization | Performance Gain | Priority |
|-------------|------------------|----------|
| Batch database writes | 10-50x faster | HIGH |
| Executemany bulk inserts | 5-10x faster | HIGH |
| SQLite WAL mode | 2-3x faster | HIGH |
| Session reuse | 10-20% faster | MEDIUM |
| Error handling | Better reliability | HIGH |
| Data validation | Better quality | MEDIUM |

**Total Expected Improvement**: 20-100x faster database operations, 10-30% faster overall collection
