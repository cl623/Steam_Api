# Codebase Function Review & Validation

## Table of Contents
1. [app.py - Flask Web Application](#apppy)
2. [market_history_collector.py - Data Collection System](#market_history_collectorpy)
3. [price_predictor.py - ML Price Prediction](#price_predictorpy)
4. [Issues & Recommendations](#issues)

---

## app.py - Flask Web Application

### **Function: `make_request(url, headers, params=None, max_retries=3)`**
**Purpose:** HTTP request helper with retry logic and exponential backoff  
**Intended Behavior:**
- Makes GET requests with retry on failure
- Handles 429 (rate limit) with exponential backoff
- Returns response object or None

**Validation:**
- ✅ Retry logic implemented
- ✅ Exponential backoff for 429 errors
- ⚠️ **ISSUE:** Returns `None` on final failure, but doesn't handle None in all callers
- ⚠️ **ISSUE:** Generic exception handling may hide specific errors

---

### **Function: `check_steam_rate_limit()`**
**Purpose:** In-memory rate limiter for Steam API (20 requests/minute)  
**Intended Behavior:**
- Tracks requests per minute
- Resets counter after 60 seconds
- Returns False if limit exceeded, True otherwise

**Validation:**
- ✅ Basic rate limiting logic correct
- ⚠️ **ISSUE:** Not thread-safe (no locking) - could cause race conditions in multi-threaded Flask
- ⚠️ **ISSUE:** Uses global variable `steam_rate_limit` - not ideal for production

---

### **Route: `@app.route('/', methods=['GET', 'POST'])` → `index()`**
**Purpose:** Main page displaying Steam market listings  
**Intended Behavior:**
- Fetches items from Steam API with pagination
- Applies filters (sell_listings, sell_price, price range)
- Sorts items by name/price/quantity
- Supports search and game selection

**Validation:**
- ✅ Pagination implemented correctly
- ✅ Filtering logic present
- ✅ Sorting works
- ⚠️ **ISSUE:** `filter_sold_7_days` is parsed but never used in filtering logic
- ⚠️ **ISSUE:** Price parsing uses regex - may fail on some price formats
- ⚠️ **ISSUE:** No error handling if `response.json()` fails
- ⚠️ **ISSUE:** `has_more` logic assumes if results == per_page, there are more (may be false)

---

### **Route: `@app.route('/api/listings')` → `get_listings()`**
**Purpose:** Alternative API endpoint for market listings (scrapes HTML)  
**Intended Behavior:**
- Scrapes Steam market HTML page
- Extracts item names, prices, quantities
- Returns JSON

**Validation:**
- ✅ Error handling present
- ⚠️ **ISSUE:** Hardcoded to `MAPLESTORY_APP_ID` - not configurable
- ⚠️ **ISSUE:** HTML scraping is fragile - Steam may change structure
- ⚠️ **ISSUE:** No rate limiting on this endpoint
- ⚠️ **ISSUE:** Uses BeautifulSoup but no error handling if HTML structure changes

---

### **Route: `@app.route('/add_to_cart', methods=['POST'])` → `add_to_cart()`**
**Purpose:** Add item to shopping cart (session-based)  
**Intended Behavior:**
- Receives item data as JSON
- Validates item data
- Checks for duplicates
- Adds to session cart
- Returns cart count and items

**Validation:**
- ✅ Duplicate checking implemented
- ✅ Session handling correct
- ✅ Error handling present
- ⚠️ **ISSUE:** Debug print statements should use logging
- ✅ Returns proper JSON responses

---

### **Route: `@app.route('/remove_from_cart', methods=['POST'])` → `remove_from_cart()`**
**Purpose:** Remove item from cart  
**Intended Behavior:**
- Receives item_name in JSON
- Removes matching item from session cart
- Returns updated cart

**Validation:**
- ✅ Logic correct
- ✅ Error handling present
- ⚠️ **ISSUE:** Debug print statements should use logging

---

### **Route: `@app.route('/cart')` → `view_cart()`**
**Purpose:** Display shopping cart page  
**Intended Behavior:**
- Retrieves cart from session
- Calculates total price
- Renders cart template

**Validation:**
- ✅ Total calculation correct
- ✅ Error handling present
- ⚠️ **ISSUE:** Debug print statements should use logging
- ⚠️ **ISSUE:** No validation that cart items have required fields

---

### **Route: `@app.route('/clear_cart', methods=['POST'])` → `clear_cart()`**
**Purpose:** Clear all items from cart  
**Intended Behavior:**
- Empties session cart
- Returns success response

**Validation:**
- ✅ Simple and correct
- ⚠️ **ISSUE:** Debug print statements should use logging

---

### **Route: `@app.route('/api/pricehistory')` → `price_history()`**
**Purpose:** Fetch price history for an item from Steam API  
**Intended Behavior:**
- Validates appid and market_hash_name parameters
- Checks rate limits
- Fetches from Steam API with cookies
- Returns JSON price history

**Validation:**
- ✅ Parameter validation
- ✅ Rate limiting check
- ✅ Error handling
- ⚠️ **ISSUE:** Debug print statements expose sensitive data (response text)
- ⚠️ **ISSUE:** Hardcoded Steam cookies may expire
- ⚠️ **ISSUE:** Special case for 400 with empty array seems odd

---

## market_history_collector.py - Data Collection System

### **Class: `RateLimiter`**

#### **Method: `__init__(self, max_requests, time_window)`**
**Purpose:** Initialize rate limiter with rolling window  
**Validation:**
- ✅ Uses deque for efficient time window tracking
- ✅ Thread-safe with lock

#### **Method: `can_make_request(self)`**
**Purpose:** Check if request can be made within rate limits  
**Validation:**
- ✅ Thread-safe
- ✅ Handles 429 retry-after logic
- ✅ Removes old requests outside window
- ✅ Correctly tracks request count

#### **Method: `handle_429(self, retry_after=None)`**
**Purpose:** Handle 429 rate limit response  
**Validation:**
- ✅ Updates retry_after time
- ✅ Exponential backoff implemented
- ✅ Caps at 5 minutes

#### **Method: `get_wait_time(self)`**
**Purpose:** Calculate wait time until next request allowed  
**Validation:**
- ✅ Correct calculation
- ✅ Thread-safe

#### **Method: `get_requests_in_window(self)`**
**Purpose:** Get count of requests in current time window  
**Validation:**
- ✅ Correct implementation
- ✅ Thread-safe

---

### **Class: `SteamMarketCollector`**

#### **Method: `__init__(self, db_path='steam_market.db')`**
**Purpose:** Initialize collector with database and rate limiters  
**Validation:**
- ✅ Initializes database
- ✅ Sets up rate limiters per game
- ✅ Creates priority queue
- ⚠️ **ISSUE:** Hardcoded Steam cookies (may expire)
- ⚠️ **ISSUE:** Default db_path is 'steam_market.db' but app.py may use different name

#### **Method: `init_database(self)`**
**Purpose:** Create database tables if they don't exist  
**Validation:**
- ✅ Creates items table with proper schema
- ✅ Creates price_history table with foreign key
- ✅ Uses UNIQUE constraints to prevent duplicates
- ✅ Proper indexing with UNIQUE constraint

#### **Method: `get_item_freshness(self, market_hash_name, game_id)`**
**Purpose:** Get priority status of item (NEW vs OLD)  
**Validation:**
- ✅ Thread-safe with lock
- ✅ Returns default NEW_ITEM if not found
- ✅ Uses composite key (game_id:market_hash_name)

#### **Method: `update_item_freshness(self, market_hash_name, game_id, is_new=True)`**
**Purpose:** Update item freshness status  
**Validation:**
- ✅ Thread-safe
- ✅ Correctly updates priority

#### **Method: `load_existing_items(self)`**
**Purpose:** Load existing items from DB and mark as OLD priority  
**Validation:**
- ✅ Loads all items from database
- ✅ Marks them as OLD (lower priority)
- ✅ Logs count

#### **Method: `check_rate_limit(self, game_id)`**
**Purpose:** Check rate limits for specific game  
**Intended Behavior:**
- Checks both minute and daily rate limits
- Waits if limit reached
- Returns True if can proceed, False otherwise

**Validation:**
- ✅ Checks both limits
- ✅ Waits appropriately
- ⚠️ **ISSUE:** Sleeps inside the function - may block thread unnecessarily
- ⚠️ **ISSUE:** Returns False but also sleeps - caller may not expect this

#### **Method: `fetch_market_listings(self, game_id)`**
**Purpose:** Fetch all market listings for a game with pagination  
**Intended Behavior:**
- Fetches all pages of results
- Handles rate limiting
- Retries on failure
- Returns list of all items

**Validation:**
- ✅ Pagination implemented
- ✅ Retry logic present
- ✅ Rate limit handling
- ✅ Random delays to avoid detection
- ⚠️ **ISSUE:** Infinite loop if total_count is wrong - should have max pages limit
- ⚠️ **ISSUE:** May take very long for games with many items

#### **Method: `fetch_price_history(self, game_id, market_hash_name)`**
**Purpose:** Fetch price history for specific item  
**Validation:**
- ✅ Rate limit checking
- ✅ Error handling
- ✅ Returns None on failure
- ✅ Logging

#### **Method: `store_item(self, market_hash_name, game_id)`**
**Purpose:** Store or update item in database  
**Validation:**
- ✅ Uses INSERT OR REPLACE
- ✅ Updates last_updated timestamp
- ✅ Returns item_id
- ⚠️ **ISSUE:** May not return correct lastrowid if item exists (SQLite behavior)

#### **Method: `store_price_history(self, item_id, price_data)`**
**Purpose:** Store price history entries, avoiding duplicates  
**Validation:**
- ✅ Uses INSERT OR IGNORE to prevent duplicates
- ✅ Handles errors gracefully
- ✅ Logs entries added
- ✅ Commits transaction

#### **Method: `calculate_dynamic_sleep(self, thread_name)`**
**Purpose:** Calculate sleep time based on rate limit usage  
**Validation:**
- ✅ Adjusts sleep based on rate limit usage
- ✅ Adds jitter
- ⚠️ **CRITICAL BUG:** Line 344 references `game_id` which is not defined in function scope!
- ⚠️ **ISSUE:** Should accept game_id as parameter

#### **Method: `worker(self)`**
**Purpose:** Worker thread that processes items from queue  
**Intended Behavior:**
- Continuously processes items from priority queue
- Fetches price history for each item
- Stores data in database
- Handles rate limits

**Validation:**
- ✅ Priority queue processing
- ✅ Rate limit checking
- ✅ Error handling
- ✅ Exponential backoff
- ⚠️ **ISSUE:** Calls `calculate_dynamic_sleep()` which has undefined variable
- ⚠️ **ISSUE:** If `fetch_price_history` returns None, item is not retried (lost)

#### **Method: `start_collection(self, num_workers=2)`**
**Purpose:** Start collection process with worker threads  
**Intended Behavior:**
- Loads existing items
- Starts worker threads
- Main loop fetches listings and adds to queue
- Waits for queue to process
- Repeats every 5 minutes

**Validation:**
- ✅ Multi-threaded workers
- ✅ Main collection loop
- ✅ Graceful shutdown handling
- ⚠️ **ISSUE:** Infinite loop - no way to stop except KeyboardInterrupt
- ⚠️ **ISSUE:** Waits for queue to be empty before next cycle - may take very long

#### **Method: `collect_market_items(self)`**
**Purpose:** Alternative collection method (appears unused)  
**Validation:**
- ⚠️ **ISSUE:** This method exists but is never called
- ⚠️ **ISSUE:** Calls `add_to_queue()` which has different signature than queue.put() used in start_collection()

#### **Method: `add_to_queue(self, game_id, market_hash_name, priority=0)`**
**Purpose:** Add item to queue with calculated priority  
**Validation:**
- ⚠️ **ISSUE:** Calculates priority based on time, but then ignores the priority parameter
- ⚠️ **ISSUE:** Uses 3-tuple `(priority, current_time, (game_id, market_hash_name))` but worker expects 2-tuple `(priority, item)`
- ⚠️ **ISSUE:** This method signature doesn't match how queue is used in `start_collection()`

---

## price_predictor.py - ML Price Prediction

### **Class: `PricePredictor`**

#### **Method: `__init__(self, db_path='market_data.db')`**
**Purpose:** Initialize predictor with database path  
**Validation:**
- ✅ Initializes models and scalers dictionaries
- ⚠️ **ISSUE:** Default db_path is 'market_data.db' but collector uses 'steam_market.db'

#### **Method: `prepare_data(self, game_id, lookback_days=30, prediction_days=7)`**
**Purpose:** Prepare training data from database  
**Intended Behavior:**
- Loads all items for game
- For each item, gets price history
- Creates features (price, moving averages, std dev, volume)
- Creates target (future price)
- Returns features, targets, item names

**Validation:**
- ✅ Feature engineering (MA7, MA30, std, volume)
- ✅ Target creation (shifted future price)
- ✅ Handles missing data
- ⚠️ **ISSUE:** Uses `game_id` but database may have different format
- ⚠️ **ISSUE:** Requires at least `lookback_days + prediction_days` data points

#### **Method: `train_model(self, game_id)`**
**Purpose:** Train Random Forest model for game  
**Validation:**
- ✅ Data preparation
- ✅ Train/test split
- ✅ Feature scaling
- ✅ Model training
- ✅ Evaluation metrics
- ✅ Saves model and scaler
- ⚠️ **ISSUE:** No validation that data is sufficient
- ⚠️ **ISSUE:** Fixed random_state for reproducibility (good)

#### **Method: `predict_price(self, game_id, item_name, current_price, current_volume)`**
**Purpose:** Predict future price for item  
**Intended Behavior:**
- Trains model if not exists
- Creates features from current price/volume
- Makes prediction

**Validation:**
- ✅ Auto-trains if needed
- ⚠️ **ISSUE:** Uses approximations for MA7, MA30, std (all use current_price or 0)
- ⚠️ **ISSUE:** Predictions may be inaccurate due to feature approximations
- ⚠️ **ISSUE:** `item_name` parameter is not used

#### **Method: `save_models(self, path='models')`**
**Purpose:** Save trained models to disk  
**Validation:**
- ✅ Creates directory if needed
- ✅ Saves both model and scaler
- ✅ Uses joblib (appropriate for sklearn)

#### **Method: `load_models(self, path='models')`**
**Purpose:** Load saved models from disk  
**Validation:**
- ✅ Checks if path exists
- ⚠️ **ISSUE:** Hardcoded game IDs 'csgo' and 'maplestory' but should use numeric IDs '730' and '216150'
- ⚠️ **ISSUE:** Doesn't match the game_id format used elsewhere

#### **Function: `main()`**
**Purpose:** Example usage of PricePredictor  
**Validation:**
- ⚠️ **ISSUE:** Uses 'csgo' and 'maplestory' instead of numeric IDs
- ⚠️ **ISSUE:** Example may not work due to game_id mismatch

---

## Issues & Recommendations

### **Critical Issues**

1. **`calculate_dynamic_sleep()` - Undefined Variable**
   - Line 344: References `game_id` which doesn't exist in function scope
   - **Fix:** Pass `game_id` as parameter or get from worker context

2. **Queue Tuple Mismatch**
   - `start_collection()` uses: `(priority, (game_id, market_hash_name))`
   - `add_to_queue()` uses: `(priority, current_time, (game_id, market_hash_name))`
   - **Fix:** Standardize queue item format

3. **Database Path Inconsistency**
   - Collector uses: `steam_market.db`
   - Predictor uses: `market_data.db`
   - **Fix:** Use consistent database path

4. **Game ID Format Mismatch**
   - Most code uses: `'216150'`, `'730'`
   - Predictor uses: `'maplestory'`, `'csgo'`
   - **Fix:** Standardize on numeric IDs everywhere

### **Medium Priority Issues**

5. **Rate Limiting Not Thread-Safe in app.py**
   - `check_steam_rate_limit()` uses global variable without lock
   - **Fix:** Add threading.Lock() or use thread-safe structure

6. **Unused Filter**
   - `filter_sold_7_days` is parsed but never used in filtering
   - **Fix:** Implement the filter or remove it

7. **Hardcoded Credentials**
   - Steam cookies hardcoded in multiple files
   - **Fix:** Move to environment variables or config file

8. **Infinite Loops**
   - `fetch_market_listings()` could loop forever if total_count wrong
   - **Fix:** Add maximum page limit

9. **Missing Error Handling**
   - Several places where `response.json()` could fail
   - **Fix:** Add try/except for JSON parsing

### **Low Priority / Code Quality**

10. **Debug Print Statements**
    - Should use logging instead of print()
    - **Fix:** Replace with proper logging

11. **Unused Method**
    - `collect_market_items()` is never called
    - **Fix:** Remove or integrate

12. **Price Prediction Feature Approximation**
    - Uses current_price for all moving averages
    - **Fix:** Fetch actual historical data for accurate features

13. **Missing Dependencies**
    - `price_predictor.py` needs: pandas, numpy, sklearn, joblib
    - Not in `dependencies.txt`
    - **Fix:** Add to dependencies file

14. **run_collector.py References Wrong Module**
    - Imports `market_data_collector` but file is `market_history_collector.py`
    - **Fix:** Update import or rename file

---

## Summary

**Total Functions Reviewed:** ~25 functions/methods  
**Critical Issues:** 4  
**Medium Issues:** 5  
**Low Priority:** 5  

**Overall Assessment:**
- Core functionality is sound
- Good error handling in most places
- Multi-threading implementation is mostly correct
- Database schema is well-designed
- Several integration issues between components need fixing
- Code quality could be improved (logging, configuration)
