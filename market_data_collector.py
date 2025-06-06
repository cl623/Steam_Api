import requests
import time
import sqlite3
import json
from datetime import datetime, timedelta
import logging
import threading
from queue import Queue
import random
import os
import urllib.parse
import sys
import codecs

# Configure logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_file = os.path.join(log_dir, f'market_data_{datetime.now().strftime("%Y%m%d")}.log')

# Create formatters
detailed_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
)
console_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
)

# Create handlers with UTF-8 encoding
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(detailed_formatter)
file_handler.setLevel(logging.DEBUG)

# Configure console handler to handle Unicode
console_handler = logging.StreamHandler(sys.stdout)  # Use stdout instead of stderr
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)

# Configure root logger
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Set default encoding for the entire application
sys.stdout.reconfigure(encoding='utf-8')  # Python 3.7+ method
sys.stderr.reconfigure(encoding='utf-8')  # Python 3.7+ method

# Steam authentication cookies
STEAM_LOGIN_SECURE = "76561198098290013||eyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwNF8yNjVGRTE0RF9GOUMxMyIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NDkyMTk0MzUsICJuYmYiOiAxNzQwNDkyMjEyLCAiaWF0IjogMTc0OTEzMjIxMiwgImp0aSI6ICIwMDBCXzI2NjhGQjM1XzYwMzdEIiwgIm9hdCI6IDE3NDg1MzU1MjIsICJydF9leHAiOiAxNzUxMTM4MTYxLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiNzEuMTcyLjQ2LjE2IiwgImlwX2NvbmZpcm1lciI6ICI3MS4xNzIuNDYuMTYiIH0.fMLDLDJtCmLofetkf5yq5Dtb32vet-CteSlGShYsgz0L6DDm29gfvpeP54sXAc2e5vHGu1a4LpFt4rbWJi5KCA"
STEAM_SESSION_ID = "e81e5ffc77a8f27479115336"

STEAM_COOKIES = {
    'sessionid': STEAM_SESSION_ID,
    'steamLoginSecure': STEAM_LOGIN_SECURE
}

# Price history cache
PRICE_HISTORY_CACHE = {}
PRICE_HISTORY_CACHE_DURATION = 300  # 5 minutes in seconds

# Database lock for thread safety
db_lock = threading.Lock()

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

class MarketDataCollector:
    def __init__(self, db_path='market_data.db'):
        self.db_path = db_path
        logger.info(f"Initializing MarketDataCollector with database: {db_path}")
        self.initialize_database()
        
        # Game configurations
        self.games = {
            'csgo': {
                'name': 'Counter-Strike 2',
                'app_id': '730',
                'market_hash_name': 'CS:GO',
                'last_update': None,
                'update_interval': 3600  # 1 hour
            },
            'maplestory': {
                'name': 'MapleStory',
                'app_id': '216150',
                'market_hash_name': 'MapleStory',
                'last_update': None,
                'update_interval': 3600  # 1 hour
            }
        }
        logger.debug(f"Configured games: {json.dumps(self.games, indent=2, cls=DateTimeEncoder)}")
        
        # Enhanced rate limiting
        self.rate_limit = {
            'minute': {
                'requests': 0,
                'last_reset': time.time(),
                'max_requests': 20,  # Maximum requests per minute
                'reset_interval': 60  # Reset interval in seconds
            },
            'day': {
                'requests': 0,
                'last_reset': datetime.now().date().isoformat(),  # Store as ISO format string
                'max_requests': 900,  # Maximum requests per day
                'reset_interval': 86400  # Reset interval in seconds
            }
        }
        logger.debug(f"Rate limit configuration: {json.dumps(self.rate_limit, indent=2)}")
        
        # Queue for items to process
        self.item_queue = Queue()
        
        # Steam session configuration
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9'
        })
        self.session.cookies.update(STEAM_COOKIES)
        
        # Start background threads
        self.running = True
        self.collector_thread = threading.Thread(target=self._collect_data_loop, name="DataCollector")
        self.processor_thread = threading.Thread(target=self._process_items_loop, name="ItemProcessor")
        self.collector_thread.daemon = True
        self.processor_thread.daemon = True
        self.collector_thread.start()
        self.processor_thread.start()
        logger.info("Background threads started")

    def initialize_database(self):
        """Initialize the database with required tables."""
        with db_lock:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:  # Increased timeout
                cursor = conn.cursor()
                
                # Enable WAL mode for better concurrency
                cursor.execute('PRAGMA journal_mode=WAL')
                
                # Create items table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        market_hash_name TEXT UNIQUE,
                        name TEXT,
                        game_id TEXT,
                        app_id TEXT,
                        last_updated TIMESTAMP
                    )
                ''')
                
                # Create price history table
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
                
                # Create indexes for better performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_market_hash_name ON items(market_hash_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_history_item_id ON price_history(item_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_history_timestamp ON price_history(timestamp)')
                
                conn.commit()

    def _get_cached_price_history(self, app_id, market_hash_name):
        """Get price history from cache if available and not expired."""
        cache_key = f"{app_id}_{market_hash_name}"
        if cache_key in PRICE_HISTORY_CACHE:
            cache_time, cache_data = PRICE_HISTORY_CACHE[cache_key]
            if time.time() - cache_time < PRICE_HISTORY_CACHE_DURATION:
                logger.debug(f"Using cached price history for {market_hash_name}")
                return cache_data
        return None

    def _set_cached_price_history(self, app_id, market_hash_name, data):
        """Cache price history data."""
        cache_key = f"{app_id}_{market_hash_name}"
        PRICE_HISTORY_CACHE[cache_key] = (time.time(), data)
        logger.debug(f"Cached price history for {market_hash_name}")

    def _check_rate_limit(self):
        """Check and update rate limiting with enhanced logic."""
        current_time = time.time()
        current_date = datetime.now().date().isoformat()
        
        # Check minute rate limit
        if current_time - self.rate_limit['minute']['last_reset'] >= self.rate_limit['minute']['reset_interval']:
            self.rate_limit['minute']['requests'] = 0
            self.rate_limit['minute']['last_reset'] = current_time
            logger.debug("Minute rate limit counter reset")
        
        # Check daily rate limit
        if current_date != self.rate_limit['day']['last_reset']:
            self.rate_limit['day']['requests'] = 0
            self.rate_limit['day']['last_reset'] = current_date
            logger.debug("Daily rate limit counter reset")
        
        # Calculate wait times
        minute_wait = 0
        day_wait = 0
        
        # More conservative rate limiting
        if self.rate_limit['minute']['requests'] >= 15:  # Reduced from 20 to 15
            minute_wait = self.rate_limit['minute']['reset_interval'] - (current_time - self.rate_limit['minute']['last_reset'])
            logger.info(f"Minute rate limit reached. Waiting {minute_wait:.2f} seconds")
        
        if self.rate_limit['day']['requests'] >= 800:  # Reduced from 900 to 800
            day_wait = self.rate_limit['day']['reset_interval'] - (current_time - time.mktime(datetime.fromisoformat(self.rate_limit['day']['last_reset']).timetuple()))
            logger.info(f"Daily rate limit reached. Waiting {day_wait:.2f} seconds")
        
        # Wait for the longer of the two wait times
        wait_time = max(minute_wait, day_wait)
        if wait_time > 0:
            time.sleep(wait_time)
            self.rate_limit['minute']['requests'] = 0
            self.rate_limit['minute']['last_reset'] = time.time()
            self.rate_limit['day']['requests'] = 0
            self.rate_limit['day']['last_reset'] = current_date
        
        # Add a longer random delay between requests (2-5 seconds)
        delay = random.uniform(2, 5)
        logger.debug(f"Adding {delay:.2f} second delay between requests")
        time.sleep(delay)
        
        # Update request counts
        self.rate_limit['minute']['requests'] += 1
        self.rate_limit['day']['requests'] += 1
        
        logger.debug(f"Current request counts - Minute: {self.rate_limit['minute']['requests']}, Day: {self.rate_limit['day']['requests']}")

    def _collect_data_loop(self):
        """Background thread for collecting market data."""
        logger.info("Starting data collection loop")
        while self.running:
            try:
                for game_id, game_config in self.games.items():
                    current_time = time.time()
                    if (game_config['last_update'] is None or 
                        current_time - game_config['last_update'] >= game_config['update_interval']):
                        
                        logger.info(f"Collecting data for {game_config['name']} (Game ID: {game_id})")
                        try:
                            self._collect_game_data(game_id)
                            self.games[game_id]['last_update'] = current_time
                            logger.debug(f"Updated last_update timestamp for {game_id} to {current_time}")
                        except Exception as e:
                            logger.error(f"Error collecting data for {game_config['name']}: {str(e)}", exc_info=True)
                            # Don't update last_update on error to retry sooner
                            continue
                        
                        # Add longer delay between games (5-10 seconds)
                        delay = random.uniform(5, 10)
                        logger.debug(f"Waiting {delay:.2f} seconds before next game")
                        time.sleep(delay)
                
                # Sleep for a while before next collection cycle
                cycle_delay = 300  # 5 minutes between cycles
                logger.debug(f"Collection cycle complete, waiting {cycle_delay} seconds before next cycle")
                time.sleep(cycle_delay)
                
            except Exception as e:
                logger.error(f"Error in collection loop: {str(e)}", exc_info=True)
                # Wait a bit longer on error before retrying
                time.sleep(60)

    def _process_items_loop(self):
        """Background thread for processing queued items with enhanced error handling."""
        logger.info("Starting item processing loop")
        processed_count = 0
        while self.running:
            try:
                if not self.item_queue.empty():
                    item_data = self.item_queue.get()
                    try:
                        self._process_item(item_data)
                        processed_count += 1
                        if processed_count % 10 == 0:  # Log progress every 10 items
                            logger.info(f"Processed {processed_count} items so far")
                    except Exception as e:
                        logger.error(f"Failed to process item {item_data.get('name', 'Unknown')}: {str(e)}")
                    finally:
                        self.item_queue.task_done()
                else:
                    # Shorter sleep when queue is empty
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"Error in processing loop: {str(e)}", exc_info=True)
                time.sleep(5)  # Wait longer on processing loop errors

    def _collect_game_data(self, game_id):
        """Collect market data for a specific game."""
        game_config = self.games[game_id]
        logger.info(f"Starting data collection for {game_config['name']}")
        
        try:
            start = 0
            count = 100  # Maximum items per request
            total_items = 0
            
            while True:
                # Fetch items from Steam Market with pagination
                url = "https://steamcommunity.com/market/search/render/"
                params = {
                    'appid': game_config['app_id'],
                    'norender': 1,
                    'count': count,
                    'start': start
                }
                
                logger.debug(f"Fetching items with params: {json.dumps(params, indent=2)}")
                self._check_rate_limit()
                response = self.session.get(url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        items = data.get('results', [])
                        if not items:  # No more items to fetch
                            break
                            
                        logger.info(f"Successfully fetched {len(items)} items for {game_config['name']} (start: {start})")
                        logger.debug(f"First item sample: {json.dumps(items[0] if items else {}, indent=2)}")
                        
                        for item in items:
                            item_data = {
                                'market_hash_name': item.get('hash_name'),
                                'name': item.get('name'),
                                'game_id': game_id,
                                'app_id': game_config['app_id'],
                                'price': item.get('sell_price_text'),
                                'volume': item.get('sell_listings', 0)
                            }
                            logger.debug(f"Queueing item: {json.dumps(item_data, indent=2)}")
                            self.item_queue.put(item_data)
                        
                        total_items += len(items)
                        start += count  # Move to next page
                        
                        # Add delay between pages
                        delay = random.uniform(2, 4)
                        logger.debug(f"Waiting {delay:.2f} seconds before fetching next page")
                        time.sleep(delay)
                    else:
                        logger.warning(f"Failed to fetch items for {game_config['name']}: {data.get('message')}")
                        break
                else:
                    logger.warning(f"Failed to fetch items for {game_config['name']}. Status code: {response.status_code}")
                    break
            
            logger.info(f"Completed data collection for {game_config['name']}. Total items collected: {total_items}")
                
        except Exception as e:
            logger.error(f"Error collecting data for {game_config['name']}: {str(e)}", exc_info=True)

    def _fetch_price_history(self, app_id, market_hash_name):
        """Fetch price history for an item with enhanced error handling and caching."""
        logger.debug(f"Fetching price history for {market_hash_name} (App ID: {app_id})")
        
        # Check cache first
        cached_data = self._get_cached_price_history(app_id, market_hash_name)
        if cached_data:
            return cached_data.get('prices', [])
        
        max_retries = 3
        retry_delay = 5  # Base delay in seconds
        
        for attempt in range(max_retries):
            try:
                # URL encode the market hash name
                encoded_hash_name = urllib.parse.quote(market_hash_name)
                url = "https://steamcommunity.com/market/pricehistory/"
                params = {
                    'appid': app_id,
                    'market_hash_name': market_hash_name,
                    'norender': 1
                }
                
                # Add required headers
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'application/json',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': f'https://steamcommunity.com/market/listings/{app_id}/{encoded_hash_name}',
                    'Origin': 'https://steamcommunity.com'
                }
                
                # Check rate limits before making request
                self._check_rate_limit()
                
                # Make the request with the session and cookies
                response = self.session.get(
                    url, 
                    params=params, 
                    headers=headers,
                    cookies=STEAM_COOKIES
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        prices = data.get('prices', [])
                        logger.debug(f"Retrieved {len(prices)} price points for {market_hash_name}")
                        # Cache the successful response
                        self._set_cached_price_history(app_id, market_hash_name, data)
                        return prices
                    else:
                        error_msg = data.get('message', 'Unknown error')
                        logger.warning(f"Failed to fetch price history: {error_msg}")
                        if 'not found' in error_msg.lower():
                            logger.info(f"Item {market_hash_name} may not exist or be available")
                            return []
                elif response.status_code == 429:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Rate limit exceeded, waiting {wait_time} seconds before retry")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.warning(f"Failed to fetch price history. Status code: {response.status_code}")
                    logger.debug(f"Response content: {response.text}")
                    logger.debug(f"Request URL: {response.url}")
                    logger.debug(f"Request headers: {headers}")
                    logger.debug(f"Request cookies: {STEAM_COOKIES}")
                
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"Error fetching price history for {market_hash_name}: {str(e)}", exc_info=True)
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying after error in {wait_time} seconds...")
                    time.sleep(wait_time)
                continue
        
        logger.error(f"Failed to fetch price history after {max_retries} attempts")
        return None

    def _process_item(self, item_data):
        """Process a single item's data with enhanced error handling."""
        logger.info(f"Processing item: {item_data['name']} ({item_data['market_hash_name']})")
        max_retries = 3
        retry_delay = 1  # Base delay in seconds
        
        for attempt in range(max_retries):
            try:
                with db_lock:
                    # Create a new connection for each attempt
                    with sqlite3.connect(self.db_path, timeout=30.0) as conn:  # Increased timeout
                        cursor = conn.cursor()
                        
                        # Update or insert item
                        cursor.execute('''
                            INSERT OR REPLACE INTO items 
                            (market_hash_name, name, game_id, app_id, last_updated)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (
                            item_data['market_hash_name'],
                            item_data['name'],
                            item_data['game_id'],
                            item_data['app_id'],
                            datetime.now()
                        ))
                        
                        item_id = cursor.lastrowid
                        logger.debug(f"Item stored with ID: {item_id}")
                        
                        # Get price history
                        price_history = self._fetch_price_history(
                            item_data['app_id'],
                            item_data['market_hash_name']
                        )
                        
                        if price_history:
                            logger.info(f"Retrieved {len(price_history)} price history points for {item_data['name']}")
                            logger.debug(f"Price history sample: {json.dumps(price_history[:2] if price_history else [], indent=2)}")
                            
                            # Store price history in batches
                            batch_size = 100
                            for i in range(0, len(price_history), batch_size):
                                batch = price_history[i:i + batch_size]
                                try:
                                    for price_data in batch:
                                        timestamp = datetime.strptime(price_data[0], '%b %d %Y %H: +0')
                                        cursor.execute('''
                                            INSERT INTO price_history 
                                            (item_id, timestamp, price, volume)
                                            VALUES (?, ?, ?, ?)
                                        ''', (
                                            item_id,
                                            timestamp,
                                            price_data[1],
                                            price_data[2]
                                        ))
                                    conn.commit()  # Commit after each batch
                                except Exception as e:
                                    logger.error(f"Error storing price point batch: {str(e)}", exc_info=True)
                                    conn.rollback()  # Rollback on error
                                    continue
                            logger.debug(f"Stored price history for item {item_id}")
                        else:
                            logger.warning(f"No price history available for {item_data['name']}")
                        
                        conn.commit()
                        logger.info(f"Successfully processed item: {item_data['name']}")
                        return  # Success, exit the retry loop
                        
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Database locked, attempt {attempt + 1}/{max_retries}. Waiting {wait_time} seconds...")
                        time.sleep(wait_time)
                        continue
                logger.error(f"Database error processing item {item_data['name']}: {str(e)}")
                raise
            except Exception as e:
                logger.error(f"Error processing item {item_data['name']}: {str(e)}", exc_info=True)
                raise

    def get_current_game(self):
        """Get the current game configuration."""
        return self.games.get('csgo', self.games['maplestory'])

    def set_game(self, game_id):
        """Set the current game."""
        if game_id in self.games:
            return self.games[game_id]
        return self.get_current_game()

    def cleanup(self):
        """Cleanup resources before shutdown."""
        logger.info("Starting cleanup process")
        self.running = False
        
        # Wait for queue to be empty
        if not self.item_queue.empty():
            logger.info("Waiting for item queue to empty...")
            self.item_queue.join()
        
        # Wait for threads to finish
        if self.collector_thread.is_alive():
            logger.debug("Waiting for collector thread to finish")
            self.collector_thread.join(timeout=30)  # Wait up to 30 seconds
        if self.processor_thread.is_alive():
            logger.debug("Waiting for processor thread to finish")
            self.processor_thread.join(timeout=30)  # Wait up to 30 seconds
        
        logger.info("Cleanup complete")