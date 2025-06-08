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
        # Initialize rate limiters with rolling windows
        self.minute_limiter = RateLimiter(max_requests=15, time_window=60)  # Reduced to 15 requests per minute
        self.day_limiter = RateLimiter(max_requests=1000, time_window=86400)
        self.item_queue = PriorityQueue()
        self.stop_event = threading.Event()
        self.item_freshness = {}
        self.freshness_lock = threading.Lock()
        self.worker_sleep_times = {
            'Worker-1': 5,  # Increased to 5 seconds
            'Worker-2': 8   # Increased to 8 seconds
        }
        
        # Initialize database
        self.init_database()
        
        # Steam API configuration
        self.steam_cookies = {
            'sessionid': 'acc776ba86880c3cca3d9697',
            'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwRF8yNjY4RkI0RV8xOEEzMyIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NDk0Nzk0MjgsICJuYmYiOiAxNzQwNzUyNzE4LCAiaWF0IjogMTc0OTM5MjcxOCwgImp0aSI6ICIwMDBCXzI2NkM1M0QyXzQ1Qzg3IiwgIm9hdCI6IDE3NDkyMzQxNTQsICJydF9leHAiOiAxNzUxODQ5MjcwLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiMTA4LjM1LjIwMS4yMjgiLCAiaXBfY29uZmlybWVyIjogIjEwOC4zNS4yMDEuMjI4IiB9.h29RihRWVwTJ3TrmDrbizVvTyHqJUgmMMPNqSsdVR_XPocAhdk0IOLBDgYYPNzHsjgYTEDj5VllBlIqpIc5oAg'
        }
        
        # Supported games
        self.games = {
            '216150': 'MapleStory',
            '730': 'Counter-Strike 2'
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
            
            # Create price_history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER,
                    timestamp TIMESTAMP,
                    price REAL,
                    volume INTEGER,
                    FOREIGN KEY (item_id) REFERENCES items (id)
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

    def check_rate_limit(self):
        """Check and update rate limits with rolling windows"""
        if not self.minute_limiter.can_make_request():
            wait_time = self.minute_limiter.get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Minute rate limit reached, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return False
            
        if not self.day_limiter.can_make_request():
            wait_time = self.day_limiter.get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Daily rate limit reached, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return False
            
        return True

    def fetch_market_listings(self, game_id):
        """Fetch market listings for a specific game"""
        try:
            logging.info(f"[{threading.current_thread().name}] Fetching market listings for game {game_id} ({self.games[game_id]})")
            url = f"https://steamcommunity.com/market/search/render/"
            params = {
                'appid': game_id,
                'norender': 1,
                'count': 100
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive'
            }
            
            response = requests.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                logging.info(f"[{threading.current_thread().name}] Successfully fetched {len(results)} items for game {game_id}")
                return results
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                self.minute_limiter.handle_429(retry_after)
                logging.warning(f"[{threading.current_thread().name}] Rate limit hit, waiting {retry_after} seconds")
                time.sleep(retry_after)
                return []
            else:
                logging.error(f"[{threading.current_thread().name}] Failed to fetch listings for game {game_id}: {response.status_code}")
                return []
        except Exception as e:
            logging.error(f"[{threading.current_thread().name}] Error fetching market listings: {str(e)}")
            return []

    def fetch_price_history(self, game_id, market_hash_name):
        """Fetch price history for a specific item"""
        if not self.check_rate_limit():
            wait_time = self.minute_limiter.get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Rate limit reached, waiting {wait_time:.2f} seconds")
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
                self.minute_limiter.handle_429(retry_after)
                logging.warning(f"[{threading.current_thread().name}] Rate limit hit, waiting {retry_after} seconds")
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

    def store_price_history(self, item_id, price_data):
        """Store price history data in database"""
        if not price_data or 'prices' not in price_data:
            return

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            entries_added = 0
            for entry in price_data['prices']:
                cursor.execute('''
                    INSERT INTO price_history (item_id, timestamp, price, volume)
                    VALUES (?, ?, ?, ?)
                ''', (item_id, entry[0], entry[1], entry[2]))
                entries_added += 1
            conn.commit()
            logging.info(f"[{threading.current_thread().name}] Stored {entries_added} price history entries in database")

    def calculate_dynamic_sleep(self, thread_name):
        """Calculate dynamic sleep time based on rate limit status"""
        base_sleep = self.worker_sleep_times.get(thread_name, 5)
        requests_in_window = self.minute_limiter.get_requests_in_window()
        
        # Increase sleep time if we're approaching the rate limit
        if requests_in_window > 12:  # If we've used more than 80% of our rate limit
            return base_sleep * 2.5
        elif requests_in_window > 8:  # If we've used more than 50% of our rate limit
            return base_sleep * 2
        elif requests_in_window > 4:  # If we've used more than 25% of our rate limit
            return base_sleep * 1.5
        
        # Add some random jitter to prevent synchronized requests
        jitter = random.uniform(-1, 1)
        return max(2, base_sleep + jitter)

    def worker(self):
        """Worker thread that processes items from the queue"""
        thread_name = threading.current_thread().name
        logging.info(f"[{thread_name}] Worker thread started")
        
        while not self.stop_event.is_set():
            try:
                # Use a shorter timeout to be more responsive to stop events
                priority, item = self.item_queue.get(timeout=0.1)
                if item is None:
                    continue

                game_id, market_hash_name = item
                logging.info(f"[{thread_name}] Processing item: {market_hash_name} (Game: {self.games[game_id]}, Priority: {'NEW' if priority == ItemPriority.NEW_ITEM else 'OLD'})")
                
                # Implement exponential backoff for rate limits
                max_retries = 3
                retry_delay = 1
                
                for attempt in range(max_retries):
                    if self.check_rate_limit():
                        price_history = self.fetch_price_history(game_id, market_hash_name)
                        if price_history:
                            item_id = self.store_item(market_hash_name, game_id)
                            self.store_price_history(item_id, price_history)
                            self.update_item_freshness(market_hash_name, game_id, is_new=False)
                            logging.info(f"[{thread_name}] Successfully processed {market_hash_name} for game {game_id}")
                            break
                    else:
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                
                self.item_queue.task_done()
                
                # Dynamic sleep based on rate limit status
                sleep_time = self.calculate_dynamic_sleep(thread_name)
                logging.debug(f"[{thread_name}] Sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
                
            except Empty:
                continue
            except Exception as e:
                logging.error(f"[{thread_name}] Error in worker thread: {str(e)}")
        
        logging.info(f"[{thread_name}] Worker thread stopping")

    def start_collection(self, num_workers=2):  # Changed default to 2 workers
        """Start the collection process with multiple worker threads"""
        logging.info(f"Starting collection with {num_workers} worker threads")
        
        # Load existing items from database
        self.load_existing_items()
        
        # Start worker threads
        threads = []
        for i in range(num_workers):
            thread = threading.Thread(target=self.worker, name=f"Worker-{i+1}")
            thread.daemon = True
            thread.start()
            threads.append(thread)
            logging.info(f"Started worker thread: {thread.name}")

        # Main collection loop
        try:
            while not self.stop_event.is_set():
                for game_id in self.games:
                    logging.info(f"Starting collection cycle for game {game_id} ({self.games[game_id]})")
                    
                    # Check rate limit before fetching listings
                    if self.check_rate_limit():
                        listings = self.fetch_market_listings(game_id)
                        for item in listings:
                            if 'hash_name' in item:
                                market_hash_name = item['hash_name']
                                priority = self.get_item_freshness(market_hash_name, game_id)
                                self.item_queue.put((priority, (game_id, market_hash_name)))
                        
                        logging.info(f"Added {len(listings)} items to queue for game {game_id}")
                    else:
                        logging.warning(f"Rate limit reached, skipping collection cycle for game {game_id}")
                
                # Wait for queue to be processed
                self.item_queue.join()
                logging.info("Queue processed, waiting 5 minutes before next cycle")
                
                # Sleep for 5 minutes before next collection cycle
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