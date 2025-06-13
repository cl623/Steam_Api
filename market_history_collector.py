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
        self.worker_sleep_times = {
            'Worker-1': 10,
            'Worker-2': 15
        }
        
        # Initialize database
        self.init_database()
        
        # Steam API configuration
        self.steam_cookies = {
            'sessionid': 'acc776ba86880c3cca3d9697',
            'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwRF8yNjY4RkI0RV8xOEEzMyIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NDk1ODY3NTgsICJuYmYiOiAxNzQwODU4ODY1LCAiaWF0IjogMTc0OTQ5ODg2NSwgImp0aSI6ICIwMDBCXzI2NkM1M0VBX0QyNjNEIiwgIm9hdCI6IDE3NDkyMzQxNTQsICJydF9leHAiOiAxNzUxODQ5MjcwLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiMTA4LjM1LjIwMS4yMjgiLCAiaXBfY29uZmlybWVyIjogIjEwOC4zNS4yMDEuMjI4IiB9.EXfkV1OdC4BOsrdS88BM6D2lI3tuLdNor8H5Hzyp-UDQ9pPmrNsflUVNHdJsovVdL9FxkyTg1FmB3G8AFadTDA'
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

    def store_price_history(self, item_id, price_data):
        """Store price history data in database, avoiding duplicates"""
        if not price_data or 'prices' not in price_data:
            return

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            entries_added = 0
            for entry in price_data['prices']:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO price_history (item_id, timestamp, price, volume)
                        VALUES (?, ?, ?, ?)
                    ''', (item_id, entry[0], entry[1], entry[2]))
                    if cursor.rowcount > 0:
                        entries_added += 1
                except sqlite3.Error as e:
                    logging.error(f"Error storing price history entry: {str(e)}")
                    continue
            
            conn.commit()
            logging.info(f"[{threading.current_thread().name}] Stored {entries_added} new price history entries in database")

    def calculate_dynamic_sleep(self, thread_name):
        """Calculate dynamic sleep time based on rate limit status"""
        base_sleep = self.worker_sleep_times.get(thread_name, 5)
        requests_in_window = self.rate_limiters[game_id]['minute'].get_requests_in_window()
        
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
                    if self.check_rate_limit(game_id):
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
                    if self.check_rate_limit(game_id):
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

    def collect_market_items(self):
        """Collect market items for all supported games"""
        while not self.stop_event.is_set():
            try:
                # Alternate between games
                for game_id, game_name in self.games.items():
                    logging.info(f"Starting collection cycle for game {game_id} ({game_name})")
                    
                    # Fetch items for current game
                    items = self.fetch_market_listings(game_id)
                    
                    if items:
                        for item in items:
                            market_hash_name = item.get('hash_name')
                            if market_hash_name:
                                # Add to queue with high priority for new items
                                self.add_to_queue(game_id, market_hash_name, priority=1)
                                logging.info(f"Added item to queue: {market_hash_name} (Game: {game_name})")
                    
                    logging.info(f"Added {len(items)} items to queue for game {game_id}")
                    
                    # Add delay between games to avoid rate limiting
                    time.sleep(random.uniform(5, 8))
                
                # Wait for queue to be processed
                self.item_queue.join()
                logging.info("Queue processed, waiting 5 minutes before next cycle")
                time.sleep(300)  # Wait 5 minutes before next cycle
                
            except Exception as e:
                logging.error(f"Error in collect_market_items: {str(e)}")
                time.sleep(60)  # Wait a minute before retrying on error

    def add_to_queue(self, game_id, market_hash_name, priority=0):
        """Add an item to the queue with priority"""
        with self.freshness_lock:
            current_time = time.time()
            last_update = self.item_freshness.get(market_hash_name, 0)
            
            # Calculate priority based on freshness
            if current_time - last_update > 3600:  # More than 1 hour old
                priority = 1
            elif current_time - last_update > 1800:  # More than 30 minutes old
                priority = 2
            else:
                priority = 3
            
            self.item_queue.put((priority, current_time, (game_id, market_hash_name)))
            self.item_freshness[market_hash_name] = current_time

if __name__ == "__main__":
    collector = SteamMarketCollector()
    collector.start_collection() 