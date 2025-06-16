import sqlite3
import threading
import time
import requests
import json
from datetime import datetime, timedelta
import logging
from queue import PriorityQueue, Empty
import os
from collections import deque
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
    handlers=[
        logging.FileHandler('market_collector.log'),
        logging.StreamHandler()
    ]
)

class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = threading.Lock()
        self.last_429_time = 0
        self.retry_after = 60  # Default retry after 60 seconds

    def can_make_request(self):
        with self.lock:
            now = time.time()
            
            # Check if we need to wait after a 429 error
            if now - self.last_429_time < self.retry_after:
                return False
            
            # Remove old requests outside the time window
            while self.requests and now - self.requests[0] > self.time_window:
                self.requests.popleft()
            
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            return False

    def handle_429(self, retry_after=None):
        with self.lock:
            self.last_429_time = time.time()
            if retry_after:
                self.retry_after = retry_after
            else:
                # Exponential backoff if no retry-after header
                self.retry_after = min(300, self.retry_after * 2)  # Max 5 minutes

    def get_wait_time(self):
        with self.lock:
            if not self.requests:
                return 0
            now = time.time()
            oldest_request = self.requests[0]
            return max(0, self.time_window - (now - oldest_request))

    def get_requests_in_window(self):
        with self.lock:
            now = time.time()
            return len([r for r in self.requests if now - r <= self.time_window])

class ItemPriority:
    NEW_ITEM = 0
    OLD_ITEM = 1

class SteamMarketCollector:
    def __init__(self, db_path='steam_market.db'):
        self.db_path = db_path
        # Initialize rate limiters with rolling windows for each game
        self.rate_limiters = {
            game_id: {
                'minute': RateLimiter(max_requests=10, time_window=60),
                'day': RateLimiter(max_requests=1000, time_window=86400)
            }
            for game_id in ['216150', '730']  # MapleStory and CS2
        }
        self.item_queue = PriorityQueue()
        self.stop_event = threading.Event()
        self.item_freshness = {}
        self.freshness_lock = threading.Lock()
        
        # Add game-specific queues and tracking
        self.games = {
            '216150': 'MapleStory',
            '730': 'Counter-Strike 2'
        }
        self.game_queues = {
            game_id: [] for game_id in self.games
        }
        self.game_queue_locks = {
            game_id: threading.Lock() for game_id in self.games
        }
        
        # Batch and page size configuration
        self.page_size = 10  # Items per API request
        self.total_batch_size = 100  # Total items in a complete batch
        self.items_per_game = self.total_batch_size // len(self.games)  # Items per game in a batch
        self.pages_per_game = self.items_per_game // self.page_size  # Pages needed per game
        
        # Add error tracking and recovery
        self.failed_items = {}  # Track failed items per game
        self.failed_items_lock = threading.Lock()
        self.max_retries = 3
        self.retry_delay = 60  # seconds
        
        # Add data validation thresholds
        self.min_price_history_entries = 5
        self.max_price_deviation = 0.5  # 50% price deviation threshold
        
        # Initialize database
        self.init_database()
        
        # Steam API configuration
        self.steam_cookies = {
            'sessionid': 'acc776ba86880c3cca3d9697',
            'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwRF8yNjY4RkI0RV8xOEEzMyIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NTAwNjkxMzMsICJuYmYiOiAxNzQxMzQxNTQ1LCAiaWF0IjogMTc0OTk4MTU0NSwgImp0aSI6ICIwMDBCXzI2NzNCMkZCXzNCRDJEIiwgIm9hdCI6IDE3NDkyMzQxNTQsICJydF9leHAiOiAxNzUxODQ5MjcwLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiMTA4LjM1LjIwMS4yMjgiLCAiaXBfY29uZmlybWVyIjogIjEwOC4zNS4yMDEuMjI4IiB9.x-XaTmJlyVmo2gDFU6x8oTt9EZ_NIkH5cehsN6CBMjgpd4DabjQjIOxqf3ZxqRZ3WYVwOG9eFAyQFXP6lkHiCA'
        }

    def init_database(self):
        """Initialize SQLite database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create items table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_hash_name TEXT NOT NULL,
                    game_id TEXT NOT NULL,
                    last_updated TIMESTAMP,
                    UNIQUE(market_hash_name, game_id)
                )
            ''')
            
            # Create price_history table with unique constraint
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER,
                    timestamp TIMESTAMP,
                    price REAL,
                    volume INTEGER,
                    FOREIGN KEY (item_id) REFERENCES items (id),
                    UNIQUE(item_id, timestamp, price, volume)
                )
            ''')
            
            conn.commit()

    def get_item_freshness(self, market_hash_name, game_id):
        """Get the freshness status of an item"""
        with self.freshness_lock:
            key = f"{game_id}:{market_hash_name}"
            return self.item_freshness.get(key, ItemPriority.NEW_ITEM)

    def update_item_freshness(self, market_hash_name, game_id, is_new=True):
        """Update the freshness status of an item"""
        with self.freshness_lock:
            key = f"{game_id}:{market_hash_name}"
            self.item_freshness[key] = ItemPriority.NEW_ITEM if is_new else ItemPriority.OLD_ITEM

    def load_existing_items(self):
        """Load existing items from database and mark them as old"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT market_hash_name, game_id 
                FROM items
            ''')
            for market_hash_name, game_id in cursor.fetchall():
                self.update_item_freshness(market_hash_name, game_id, is_new=False)
            logging.info(f"Loaded {len(self.item_freshness)} existing items from database")

    def check_rate_limit(self, game_id):
        """Check and update rate limits with rolling windows for specific game"""
        if not self.rate_limiters[game_id]['minute'].can_make_request():
            wait_time = self.rate_limiters[game_id]['minute'].get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Minute rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return False
            
        if not self.rate_limiters[game_id]['day'].can_make_request():
            wait_time = self.rate_limiters[game_id]['day'].get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Daily rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return False
            
        return True

    def fetch_market_listings(self, game_id):
        """Fetch market listings for a specific game with pagination and retry logic"""
        all_results = []
        start = 0
        count = 100  # Steam's maximum per page
        max_retries = 3
        retry_delay = 5

        while True:
            for retry in range(max_retries):
                try:
                    if not self.check_rate_limit(game_id):
                        wait_time = self.rate_limiters[game_id]['minute'].get_wait_time()
                        logging.warning(f"[{threading.current_thread().name}] Rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
                        time.sleep(wait_time)
                        continue

                    # Add initial delay before first request
                    if start == 0:
                        time.sleep(random.uniform(2, 4))

                    logging.info(f"[{threading.current_thread().name}] Fetching market listings for game {game_id} ({self.games[game_id]}) - Page {start//count + 1}")
                    url = f"https://steamcommunity.com/market/search/render/"
                    params = {
                        'appid': game_id,
                        'norender': 1,
                        'count': count,
                        'start': start,
                        'search_descriptions': 1
                    }
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        'Accept': 'application/json',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Connection': 'keep-alive',
                        'Referer': f'https://steamcommunity.com/market/search?appid={game_id}'
                    }
                    
                    response = requests.get(url, params=params, headers=headers, cookies=self.steam_cookies)
                    
                    if response.status_code == 200:
                        data = response.json()
                        results = data.get('results', [])
                        total_count = data.get('total_count', 0)
                        
                        if not results:
                            logging.info(f"[{threading.current_thread().name}] No more results for game {game_id}")
                            return all_results
                        
                        all_results.extend(results)
                        logging.info(f"[{threading.current_thread().name}] Successfully fetched {len(results)} items for game {game_id} (Total: {len(all_results)}/{total_count})")
                        
                        # Add a longer delay between pages to avoid rate limiting
                        time.sleep(random.uniform(3, 5))
                        
                        # Move to next page
                        start += count
                        if start >= total_count:
                            return all_results
                        break
                        
                    elif response.status_code == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        self.rate_limiters[game_id]['minute'].handle_429(retry_after)
                        logging.warning(f"[{threading.current_thread().name}] Rate limit hit for {self.games[game_id]}, waiting {retry_after} seconds")
                        time.sleep(retry_after)
                        continue
                    else:
                        logging.error(f"[{threading.current_thread().name}] Failed to fetch listings for game {game_id}: {response.status_code}")
                        if retry < max_retries - 1:
                            time.sleep(retry_delay * (retry + 1))
                            continue
                        return all_results
                        
                except Exception as e:
                    logging.error(f"[{threading.current_thread().name}] Error fetching market listings: {str(e)}")
                    if retry < max_retries - 1:
                        time.sleep(retry_delay * (retry + 1))
                        continue
                    return all_results

        return all_results

    def fetch_price_history(self, game_id, market_hash_name):
        """Fetch price history for a specific item"""
        if not self.check_rate_limit(game_id):
            wait_time = self.rate_limiters[game_id]['minute'].get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return None

        try:
            logging.info(f"[{threading.current_thread().name}] Fetching price history for {market_hash_name} (Game: {self.games[game_id]})")
            url = "https://steamcommunity.com/market/pricehistory/"
            params = {
                'appid': game_id,
                'market_hash_name': market_hash_name,
                'currency': 1
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive'
            }
            
            response = requests.get(url, params=params, headers=headers, cookies=self.steam_cookies)
            
            if response.status_code == 200:
                data = response.json()
                if 'prices' in data:
                    logging.info(f"[{threading.current_thread().name}] Successfully fetched {len(data['prices'])} price history entries for {market_hash_name}")
                return data
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                self.rate_limiters[game_id]['minute'].handle_429(retry_after)
                logging.warning(f"[{threading.current_thread().name}] Rate limit hit for {self.games[game_id]}, waiting {retry_after} seconds")
                time.sleep(retry_after)
                return None
            else:
                logging.error(f"[{threading.current_thread().name}] Failed to fetch price history for {market_hash_name}: {response.status_code}")
                return None
        except Exception as e:
            logging.error(f"[{threading.current_thread().name}] Error fetching price history: {str(e)}")
            return None

    def store_item(self, market_hash_name, game_id):
        """Store or update item in database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO items (market_hash_name, game_id, last_updated)
                VALUES (?, ?, ?)
            ''', (market_hash_name, game_id, datetime.now()))
            conn.commit()
            return cursor.lastrowid

    def validate_price_history(self, price_history):
        """Validate price history data before storage"""
        if not price_history or 'prices' not in price_history:
            return False
            
        prices = price_history['prices']
        if len(prices) < self.min_price_history_entries:
            return False
            
        # Check for price anomalies
        try:
            # Steam API returns price history as [timestamp, price, volume]
            price_values = [float(entry[1]) for entry in prices]  # Price is at index 1
            avg_price = sum(price_values) / len(price_values)
            max_deviation = max(abs(p - avg_price) / avg_price for p in price_values)
            
            if max_deviation > self.max_price_deviation:
                logging.warning(f"Price history contains anomalous prices (max deviation: {max_deviation:.2%})")
                return False
                
            return True
        except (ValueError, IndexError) as e:
            logging.error(f"Error validating price history: {str(e)}")
            return False

    def store_price_history(self, item_id, price_history):
        """Store price history with validation"""
        if not self.validate_price_history(price_history):
            logging.warning(f"Skipping invalid price history for item_id {item_id}")
            return False
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for entry in price_history['prices']:
                    # Steam API returns price history as [timestamp, price, volume]
                    timestamp, price, volume = entry
                    cursor.execute('''
                        INSERT INTO price_history (item_id, price, volume, timestamp)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        item_id,
                        float(price),
                        int(volume),
                        int(timestamp)
                    ))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Error storing price history: {str(e)}")
            return False

    def calculate_dynamic_sleep(self, thread_name):
        """Calculate dynamic sleep time based on rate limit status"""
        base_sleep = 5  # Default base_sleep
        
        # Get the maximum requests in window across all games
        max_requests = 0
        for game_id in self.games:
            requests_in_window = self.rate_limiters[game_id]['minute'].get_requests_in_window()
            max_requests = max(max_requests, requests_in_window)
        
        # Increase sleep time if we're approaching the rate limit
        if max_requests > 12:  # If we've used more than 80% of our rate limit
            return base_sleep * 2.5
        elif max_requests > 8:  # If we've used more than 50% of our rate limit
            return base_sleep * 2
        elif max_requests > 4:  # If we've used more than 25% of our rate limit
            return base_sleep * 1.5
        
        # Add some random jitter to prevent synchronized requests
        jitter = random.uniform(-1, 1)
        return max(2, base_sleep + jitter)

    def add_to_queue(self, game_id, market_hash_name, priority=0):
        """Add an item to the game-specific queue with priority"""
        with self.game_queue_locks[game_id]:
            self.game_queues[game_id].append((priority, market_hash_name))
            logging.debug(f"Added {market_hash_name} to {self.games[game_id]} queue")

    def get_next_item(self):
        """Get the next item to process based on worker assignment"""
        thread_name = threading.current_thread().name
        worker_num = int(thread_name.split('-')[1])  # Worker-1 -> 1, Worker-2 -> 2, etc.
        
        # Map worker number to game_id
        game_ids = list(self.games.keys())
        if 1 <= worker_num <= len(game_ids):
            assigned_game = game_ids[worker_num - 1]
            with self.game_queue_locks[assigned_game]:
                if self.game_queues[assigned_game]:
                    priority, market_hash_name = self.game_queues[assigned_game].pop(0)
                    return priority, (assigned_game, market_hash_name)
        
        return None, None

    def fetch_batch_for_game(self, game_id):
        """Fetch a single page (10 items) for a specific game"""
        if not self.check_rate_limit(game_id):
            logging.warning(f"Rate limit reached for {self.games[game_id]}, skipping page")
            return []
            
        items_fetched = []
        try:
            listings = self.fetch_market_listings(game_id)
            for item in listings[:self.page_size]:  # Only take page_size items
                if 'hash_name' in item:
                    market_hash_name = item['hash_name']
                    priority = self.get_item_freshness(market_hash_name, game_id)
                    self.add_to_queue(game_id, market_hash_name, priority)
                    items_fetched.append(market_hash_name)
        except Exception as e:
            logging.error(f"Error fetching page for {self.games[game_id]}: {str(e)}")
            
        return items_fetched

    def worker(self):
        """Worker thread that processes items from the queue"""
        thread_name = threading.current_thread().name
        logging.info(f"[{thread_name}] Worker thread started")
        
        while not self.stop_event.is_set():
            try:
                # Get next item using round-robin
                priority, item = self.get_next_item()
                if item is None:
                    time.sleep(1)  # Sleep briefly if no items available
                    continue

                game_id, market_hash_name = item
                logging.info(f"[{thread_name}] Processing item: {market_hash_name} (Game: {self.games[game_id]}, Priority: {'NEW' if priority == ItemPriority.NEW_ITEM else 'OLD'})")
                
                # Check if this item has failed before
                with self.failed_items_lock:
                    if game_id in self.failed_items and market_hash_name in self.failed_items[game_id]:
                        retry_count = self.failed_items[game_id][market_hash_name]
                        if retry_count >= self.max_retries:
                            logging.warning(f"[{thread_name}] Skipping {market_hash_name} after {retry_count} failed attempts")
                            continue
                
                # Implement exponential backoff for rate limits
                max_retries = 3
                retry_delay = 1
                
                for attempt in range(max_retries):
                    if self.check_rate_limit(game_id):
                        price_history = self.fetch_price_history(game_id, market_hash_name)
                        if price_history:
                            item_id = self.store_item(market_hash_name, game_id)
                            if price_history.get('prices'):
                                if self.store_price_history(item_id, price_history):
                                    self.update_item_freshness(market_hash_name, game_id, is_new=False)
                                    # Clear failed status if successful
                                    with self.failed_items_lock:
                                        if game_id in self.failed_items:
                                            self.failed_items[game_id].pop(market_hash_name, None)
                                    logging.info(f"[{thread_name}] Successfully processed {market_hash_name} for game {game_id} with {len(price_history['prices'])} price entries")
                                else:
                                    self.record_failed_item(game_id, market_hash_name)
                            else:
                                logging.warning(f"[{thread_name}] No price history data found for {market_hash_name}")
                                self.record_failed_item(game_id, market_hash_name)
                            break
                        else:
                            logging.warning(f"[{thread_name}] Failed to fetch price history for {market_hash_name}")
                            self.record_failed_item(game_id, market_hash_name)
                    else:
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                
                # Dynamic sleep based on rate limit status
                sleep_time = self.calculate_dynamic_sleep(thread_name)
                logging.debug(f"[{thread_name}] Sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
                
            except Exception as e:
                logging.error(f"[{thread_name}] Error in worker thread: {str(e)}")
        
        logging.info(f"[{thread_name}] Worker thread stopping")

    def record_failed_item(self, game_id, market_hash_name):
        """Record a failed item for retry"""
        with self.failed_items_lock:
            if game_id not in self.failed_items:
                self.failed_items[game_id] = {}
            self.failed_items[game_id][market_hash_name] = self.failed_items[game_id].get(market_hash_name, 0) + 1

    def get_queue_sizes(self):
        """Get the current size of all game queues"""
        sizes = {}
        for game_id in self.games:
            with self.game_queue_locks[game_id]:
                sizes[game_id] = len(self.game_queues[game_id])
        return sizes

    def should_pause_fetching(self):
        """Check if we should pause fetching to let workers catch up"""
        queue_sizes = self.get_queue_sizes()
        max_queue_size = max(queue_sizes.values())
        min_queue_size = min(queue_sizes.values())
        
        # Log queue sizes and failed items
        with self.failed_items_lock:
            failed_counts = {game_id: len(items) for game_id, items in self.failed_items.items()}
        logging.info(f"Current queue sizes: {queue_sizes}, Failed items: {failed_counts}")
        
        # Pause if queue sizes are too imbalanced
        queue_imbalance = max_queue_size - min_queue_size
        return queue_imbalance > self.page_size

    def start_collection(self):
        """Start the collection process with one worker per game"""
        num_workers = len(self.games)
        logging.info(f"Starting collection with {num_workers} worker threads (one per game)")
        logging.info(f"Batch configuration: {self.total_batch_size} total items, {self.items_per_game} per game, {self.pages_per_game} pages per game")
        
        # Load existing items from database
        self.load_existing_items()
        
        # Start worker threads
        threads = []
        for i in range(num_workers):
            thread = threading.Thread(target=self.worker, name=f"Worker-{i+1}")
            thread.daemon = True
            thread.start()
            threads.append(thread)
            logging.info(f"Started worker thread: {thread.name} for {self.games[list(self.games.keys())[i]]}")

        # Main collection loop
        try:
            while not self.stop_event.is_set():
                # Check if we should pause fetching
                if self.should_pause_fetching():
                    logging.info("Queue sizes imbalanced, pausing to let workers catch up")
                    time.sleep(30)
                    continue
                
                # Track pages fetched per game
                pages_per_game = {game_id: 0 for game_id in self.games}
                total_pages_fetched = 0
                
                # Fetch complete batch (100 items total)
                while total_pages_fetched < self.pages_per_game * len(self.games):
                    # Check if any game has reached its page limit
                    if all(pages_per_game[game_id] >= self.pages_per_game for game_id in self.games):
                        break
                        
                    for game_id in self.games:
                        # Skip if we've fetched enough pages for this game
                        if pages_per_game[game_id] >= self.pages_per_game:
                            continue
                            
                        items_fetched = self.fetch_batch_for_game(game_id)
                        pages_per_game[game_id] += 1
                        total_pages_fetched += 1
                        
                        logging.info(f"Fetched page {pages_per_game[game_id]}/{self.pages_per_game} for {self.games[game_id]}: {len(items_fetched)} items")
                        logging.info(f"Current queue sizes: {self.get_queue_sizes()}, Failed items: {self.failed_items}")
                        
                        # Check rate limits after each page
                        if self.should_pause_fetching():
                            logging.info("Rate limit or queue imbalance detected, pausing")
                            time.sleep(30)
                            break
                
                # Wait for workers to process the batch
                while any(len(queue) > 0 for queue in self.game_queues.values()):
                    time.sleep(5)
                
                logging.info("Batch complete, waiting 5 minutes before next batch")
                time.sleep(300)
                
        except KeyboardInterrupt:
            logging.info("Stopping collection...")
            self.stop_event.set()
            
            # Wait for all threads to finish
            for thread in threads:
                thread.join()
                logging.info(f"Worker thread {thread.name} stopped")

if __name__ == "__main__":
    collector = SteamMarketCollector()
    collector.start_collection() 