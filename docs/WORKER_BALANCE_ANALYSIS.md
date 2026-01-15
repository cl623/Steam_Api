# Worker Balance Analysis: Market Listings vs Price History

## Current Architecture

### Two-Phase Collection Process

The collector uses a **two-phase approach** with distinct responsibilities:

#### Phase 1: Market Listings Fetch (Main Thread)
- **Who**: Main thread in `start_collection()`
- **What**: Discovers all available items for a game
- **When**: Periodically, in cycles
- **Rate Limit**: Uses same rate limiter as price history (8 req/min)

#### Phase 2: Price History Fetch (Worker Threads)
- **Who**: 3 worker threads (configurable)
- **What**: Fetches price history for each queued item
- **When**: Continuously, as long as queue has items
- **Rate Limit**: Uses same rate limiter as listings (8 req/min)

---

## Current Flow

```
┌─────────────────────────────────────────────────────────────┐
│ MAIN THREAD (start_collection)                               │
├─────────────────────────────────────────────────────────────┤
│ 1. Fetch market listings (all items for game)               │
│    - Uses rate limiter (8 req/min)                           │
│    - Paginated (100 items per page)                         │
│    - Adds all items to priority queue                       │
│                                                              │
│ 2. Wait for queue to be processed                           │
│    - Checks every 30 seconds                                 │
│    - Max 5 minutes wait (10 checks)                         │
│                                                              │
│ 3. When queue empty → Start next cycle                      │
│    - Small 10s delay                                         │
│    - Repeat from step 1                                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │ Priority    │
                    │ Queue       │
                    └─────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Worker-1     │  │ Worker-2     │  │ Worker-3     │
├──────────────┤  ├──────────────┤  ├──────────────┤
│ Pull item    │  │ Pull item    │  │ Pull item    │
│ from queue   │  │ from queue   │  │ from queue   │
│              │  │              │  │              │
│ Fetch price  │  │ Fetch price  │  │ Fetch price  │
│ history      │  │ history      │  │ history      │
│              │  │              │  │              │
│ Store in DB  │  │ Store in DB  │  │ Store in DB  │
│              │  │              │  │              │
│ Sleep        │  │ Sleep        │  │ Sleep        │
│ (dynamic)    │  │ (dynamic)    │  │ (dynamic)    │
└──────────────┘  └──────────────┘  └──────────────┘
```

---

## Rate Limit Sharing

### Critical Issue: **Shared Rate Limiter**

Both operations share the **same rate limiter**:
- Market listings fetch: Uses `check_rate_limit(game_id)`
- Price history fetch: Uses `check_rate_limit(game_id)`
- **Total budget**: 8 requests/minute

### Current Behavior

1. **Market Listings Fetch**:
   - Happens in main thread
   - Fetches all items (could be 1000s)
   - Uses multiple requests (pagination)
   - **Blocks workers** while fetching (main thread is busy)

2. **Price History Fetch**:
   - Happens in worker threads
   - One request per item
   - **Competes with listings** for rate limit budget

### Problem: **No Explicit Balance**

The current implementation doesn't explicitly balance between the two:

- **Market listings** can consume rate limit budget during fetch
- **Workers** consume rate limit budget continuously
- **No prioritization**: Both compete equally for the 8 req/min budget
- **Main thread blocking**: While fetching listings, workers may be idle if rate limit is hit

---

## Detailed Flow Analysis

### Scenario 1: Initial Collection (Empty Queue)

```
Time 0s:   Main thread starts fetching listings
           - Request 1: Page 1 (100 items)
           - Rate limit: 7/8 remaining
           - Request 2: Page 2 (100 items)  
           - Rate limit: 6/8 remaining
           - ... continues pagination ...
           - Adds 1000 items to queue
           
Time 30s:  Main thread finishes, adds items to queue
           Workers start processing queue
           - Worker-1: Fetches price history for item 1
           - Rate limit: 5/8 remaining
           - Worker-2: Fetches price history for item 2
           - Rate limit: 4/8 remaining
           - Worker-3: Fetches price history for item 3
           - Rate limit: 3/8 remaining
           - ... workers continue ...
           
Time 60s:  Rate limit window resets
           Workers continue processing queue
           Main thread waits for queue to empty
```

### Scenario 2: Continuous Operation (Queue Has Items)

```
Main Thread:
  - Checks if queue is empty (every 30s)
  - If queue has items → waits
  - If queue empty → fetches new listings
  
Workers:
  - Continuously pull items from queue
  - Fetch price history
  - Store in database
  - Sleep dynamically based on rate limit
```

---

## Current Balance Mechanism

### Implicit Balance (Not Explicit)

1. **Priority Queue**: New items get priority 0, old items get priority 1
   - New items processed first
   - But doesn't affect rate limit allocation

2. **Main Thread Waiting**: 
   - Main thread waits for queue to empty before fetching new listings
   - This prevents overwhelming the queue
   - But doesn't balance rate limit usage

3. **Dynamic Sleep**:
   - Workers sleep based on rate limit capacity
   - If rate limit is low, workers sleep longer
   - This helps, but doesn't reserve budget for listings

4. **Rate Limit Check**:
   - Both operations check rate limit before making request
   - First-come-first-served for rate limit budget
   - No reservation or priority

---

## Issues with Current Balance

### Issue 1: **No Rate Limit Reservation**
- Market listings fetch can consume entire rate limit budget
- Workers may be starved during listings fetch
- No guarantee that workers get rate limit budget

### Issue 2: **Main Thread Blocking**
- While main thread fetches listings, it's not processing queue
- Workers may be idle if rate limit is consumed by listings
- No parallel processing of listings and price history

### Issue 3: **Unpredictable Timing**
- Time between listing fetches depends on queue processing speed
- If queue is large, listings fetch happens infrequently
- If queue is small, listings fetch happens frequently
- No fixed schedule

### Issue 4: **Rate Limit Competition**
- Both operations compete for same 8 req/min budget
- No explicit allocation (e.g., "2 req/min for listings, 6 req/min for price history")
- Could lead to inefficient usage

---

## Current Behavior Summary

### Market Listings Fetch
- **Frequency**: Variable (depends on queue processing speed)
- **Rate Limit Usage**: Variable (could use 1-8 requests per cycle)
- **Blocking**: Yes (main thread blocks during fetch)
- **Priority**: Implicit (happens when queue is empty)

### Price History Fetch
- **Frequency**: Continuous (as long as queue has items)
- **Rate Limit Usage**: Continuous (workers consume budget)
- **Blocking**: No (workers run in parallel)
- **Priority**: Implicit (new items prioritized in queue)

### Balance Mechanism
- **Explicit Balance**: ❌ None
- **Implicit Balance**: ✅ Main thread waits for queue
- **Rate Limit Allocation**: ❌ First-come-first-served
- **Coordination**: ❌ No explicit coordination

---

## Potential Improvements (For Future Consideration)

### Option 1: Separate Rate Limiters
- Dedicated rate limiter for listings (e.g., 1 req/min)
- Dedicated rate limiter for price history (e.g., 7 req/min)
- Explicit budget allocation

### Option 2: Scheduled Listings Fetch
- Fetch listings on fixed schedule (e.g., every hour)
- Independent of queue status
- Workers always have budget for price history

### Option 3: Rate Limit Reservation
- Reserve budget for listings (e.g., 2 req/min)
- Workers use remaining budget (e.g., 6 req/min)
- Better predictability

### Option 4: Parallel Processing
- Fetch listings in background thread
- Don't block main thread
- Better utilization

---

## Conclusion

**Current State**: The collector uses an **implicit balance** mechanism:
- Main thread fetches listings when queue is empty
- Workers continuously process queue
- Both share the same rate limiter (8 req/min)
- No explicit allocation or prioritization

**Effectiveness**: Works, but not optimal:
- ✅ Prevents queue overflow (main thread waits)
- ✅ Prioritizes new items (priority queue)
- ❌ No explicit rate limit allocation
- ❌ Main thread can block workers
- ❌ Unpredictable timing

**Recommendation**: Current approach is functional but could benefit from explicit rate limit allocation or scheduled listings fetch for better predictability and efficiency.
