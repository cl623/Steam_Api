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
import os
log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'market_collector.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
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
            now = time.time()
            
            # Check if we're still in 429 retry period
            if now - self.last_429_time < self.retry_after:
                remaining = self.retry_after - (now - self.last_429_time)
                return max(0, remaining)
            
            # If no requests in queue, no wait needed
            if not self.requests:
                return 0
            
            # Calculate wait time based on oldest request
            oldest_request = self.requests[0]
            wait_time = max(0, self.time_window - (now - oldest_request))
            return wait_time

    def get_requests_in_window(self):
        with self.lock:
            now = time.time()
            return len([r for r in self.requests if now - r <= self.time_window])

class ItemPriority:
    NEW_ITEM = 0
    OLD_ITEM = 1

class SteamMarketCollector:
    def __init__(self, db_path=None, steam_cookies=None, update_interval_hours=12, pause_file=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'market_data.db')
        self.db_path = db_path
        self.update_interval_hours = update_interval_hours  # How often to update price history (default: 12 hours)
        self.pause_file = pause_file  # Path to pause file (if file exists, pause collection)
        
        # Separate rate limiters for different operations
        # This allows explicit budget allocation and better balance
        # Total budget: 8 requests/minute (80% of Steam's 10 req/min limit)
        # Allocation:
        #   - Listings: 1 req/min (for discovering new items) = 1,440/day
        #   - Price History: 7 req/min (for continuous data collection) = 10,080/day
        # Daily limit: 12,000 requests/day (allows full utilization of per-minute limits)
        # Steam's actual daily limits are estimated at 10k-20k+ based on community testing
        self.rate_limiters = {
            game_id: {
                'minute': RateLimiter(max_requests=8, time_window=60),  # Overall limit
                'day': RateLimiter(max_requests=12000, time_window=86400),  # Daily limit (increased from 900)
                # Separate limiters for explicit budget allocation
                'listings': RateLimiter(max_requests=1, time_window=60),  # 1 req/min for listings
                'price_history': RateLimiter(max_requests=7, time_window=60)  # 7 req/min for price history
            }
            for game_id in [
                # '216150',  # MapleStory - commented out, focusing on CS2
                '730'  # Counter-Strike 2
            ]
        }
        self.item_queue = PriorityQueue()
        self.stop_event = threading.Event()
        self.item_freshness = {}
        self.freshness_lock = threading.Lock()
        self._last_empty_log = {}  # Track last empty queue log time per worker
        self._empty_log_lock = threading.Lock()  # Lock for empty log tracking
        
        # Calculate optimal sleep times for constant stream
        # With 8 requests/minute and multiple workers, we need to coordinate to stay under the limit
        # 60 seconds / 8 requests = 7.5 seconds per request
        # With 3-4 workers, we stagger their sleep times to prevent synchronization
        # Dynamic sleep calculation adjusts based on rate limit status
        optimal_sleep = 60 / 8  # ~7.5 seconds between requests
        self.worker_sleep_times = {
            'Worker-1': optimal_sleep,
            'Worker-2': optimal_sleep + 0.5,  # Slight offset to prevent synchronization
            'Worker-3': optimal_sleep + 1.0,  # Additional offset for 3rd worker
            'Worker-4': optimal_sleep + 1.5,  # Additional offset for 4th worker
        }
        
        # Initialize database
        self.init_database()
        
        # Steam API configuration - use provided cookies or get from config (same priority as web app)
        if steam_cookies:
            self.steam_cookies = steam_cookies
        else:
            # Try to get from environment variables first (same priority as web app)
            cookie_string = os.getenv('STEAM_COOKIE_STRING', '')
            sessionid = os.getenv('STEAM_SESSIONID', '')
            steamLoginSecure = os.getenv('STEAM_LOGIN_SECURE', '')
            
            if cookie_string:
                # Parse cookie string (same logic as web app)
                self.steam_cookies = self._parse_cookie_string(cookie_string)
                logging.info("[Collector] Loaded cookies from STEAM_COOKIE_STRING environment variable")
            elif sessionid and steamLoginSecure:
                self.steam_cookies = {
                    'sessionid': sessionid,
                    'steamLoginSecure': steamLoginSecure
                }
                # Add optional cookies from env if available
                if os.getenv('STEAM_BROWSERID'):
                    self.steam_cookies['browserid'] = os.getenv('STEAM_BROWSERID')
                if os.getenv('STEAM_COUNTRY'):
                    self.steam_cookies['steamCountry'] = os.getenv('STEAM_COUNTRY')
                if os.getenv('STEAM_WEB_TRADE_ELIGIBILITY'):
                    self.steam_cookies['webTradeEligibility'] = os.getenv('STEAM_WEB_TRADE_ELIGIBILITY')
                logging.info("[Collector] Loaded cookies from environment variables")
            else:
                # Fall back to config file (same as web app)
                try:
                    from app.config import DEFAULT_STEAM_COOKIES
                    self.steam_cookies = DEFAULT_STEAM_COOKIES.copy()
                    logging.info("[Collector] Loaded cookies from app/config.py")
                except ImportError:
                    # Fallback if config not available
                    logging.warning("[Collector] Could not import app.config, using hardcoded defaults")
                    self.steam_cookies = {
                        'sessionid': 'cd378381e917696bf316041b',
                        'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAxM18yNzg3M0Q1MV8xOTBCQiIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NjgyODU5MTAsICJuYmYiOiAxNzU5NTU3ODIwLCAiaWF0IjogMTc2ODE5NzgyMCwgImp0aSI6ICIwMDBCXzI3ODczRDY4XzVDNDlGIiwgIm9hdCI6IDE3NjgxMDAwMDIsICJydF9leHAiOiAxNzg2MzkxNzM0LCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiNzEuMTcyLjM3LjEwNyIsICJpcF9jb25maXJtZXIiOiAiNzEuMTcyLjM3LjEwNyIgfQ.ej1Sd8eBr7U1DLurjGsI9pMXjuGO22VHYl15O2SxrpdzdA1KH9XyMJ5ZVmefF5JF56kKsl_7dwndnUgCFYvYBg'
                    }
        
        # Supported games
        self.games = {
            # '216150': 'MapleStory',  # Commented out - focusing on CS2 data collection
            '730': 'Counter-Strike 2'
        }
        
        # Validate cookies at startup (same validation as web app)
        self._validate_cookies()
    
    def _parse_cookie_string(self, cookie_string):
        """Parse a cookie string into a dictionary (same logic as web app)"""
        cookies = {}
        if not cookie_string:
            return cookies
        for cookie_pair in cookie_string.split('; '):
            if '=' in cookie_pair:
                name, value = cookie_pair.split('=', 1)
                cookies[name.strip()] = value.strip()
        return cookies
    
    def _validate_cookies(self):
        """Validate cookies at startup (same validation as web app)"""
        if not self.steam_cookies.get('sessionid') or not self.steam_cookies.get('steamLoginSecure'):
            logging.error("[Collector] Missing required cookies: sessionid and steamLoginSecure are required")
            raise ValueError("Missing required Steam cookies. Please configure cookies in app/config.py or via environment variables.")
        
        # Validate token audience
        try:
            from app.utils import validate_steam_token_audience
            steamLoginSecure = self.steam_cookies.get('steamLoginSecure', '')
            is_valid, audience, error_msg = validate_steam_token_audience(steamLoginSecure)
            if not is_valid:
                logging.error(f"[Collector] Cookie validation failed: {error_msg}")
                logging.error(f"[Collector] Token audience: {audience}")
                logging.error("[Collector] Please update cookies in app/config.py using:")
                logging.error("[Collector]   python scripts/test_cookies.py --cookie-string \"...\" --auto-update-config")
                raise ValueError(f"Invalid cookie token audience: {error_msg}")
            logging.info(f"[Collector] Cookie validation passed. Token audience: {audience}")
        except ImportError:
            logging.warning("[Collector] Could not import token validation from app.utils, skipping validation")
        except Exception as e:
            logging.warning(f"[Collector] Cookie validation error: {e}, continuing anyway")
    
    def _parse_cookie_string(self, cookie_string):
        """Parse a cookie string into a dictionary (same logic as web app)"""
        cookies = {}
        if not cookie_string:
            return cookies
        for cookie_pair in cookie_string.split('; '):
            if '=' in cookie_pair:
                name, value = cookie_pair.split('=', 1)
                cookies[name.strip()] = value.strip()
        return cookies
    
    def _validate_cookies(self):
        """Validate cookies at startup (same validation as web app)"""
        if not self.steam_cookies.get('sessionid') or not self.steam_cookies.get('steamLoginSecure'):
            logging.error("[Collector] Missing required cookies: sessionid and steamLoginSecure are required")
            raise ValueError("Missing required Steam cookies. Please configure cookies in app/config.py or via environment variables.")
        
        # Validate token audience
        try:
            from app.utils import validate_steam_token_audience
            steamLoginSecure = self.steam_cookies.get('steamLoginSecure', '')
            is_valid, audience, error_msg = validate_steam_token_audience(steamLoginSecure)
            if not is_valid:
                logging.error(f"[Collector] Cookie validation failed: {error_msg}")
                logging.error(f"[Collector] Token audience: {audience}")
                logging.error("[Collector] Please update cookies in app/config.py using:")
                logging.error("[Collector]   python scripts/test_cookies.py --cookie-string \"...\" --auto-update-config")
                raise ValueError(f"Invalid cookie token audience: {error_msg}")
            logging.info(f"[Collector] Cookie validation passed. Token audience: {audience}")
        except ImportError:
            logging.warning("[Collector] Could not import token validation from app.utils, skipping validation")
        except Exception as e:
            logging.warning(f"[Collector] Cookie validation error: {e}, continuing anyway")

    def init_database(self):
        """Initialize SQLite database with required tables and indexes"""
        with sqlite3.connect(self.db_path) as conn:
            # Optimize SQLite for better performance
            conn.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging for better concurrency
            conn.execute('PRAGMA synchronous=NORMAL')  # Faster than FULL, still safe
            conn.execute('PRAGMA cache_size=-64000')  # 64MB cache (negative = KB)
            conn.execute('PRAGMA temp_store=MEMORY')  # Store temp tables in memory
            conn.execute('PRAGMA mmap_size=268435456')  # 256MB memory-mapped I/O
            
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
            
            # Create indexes for better query performance
            # Index on items table for lookups by game_id and market_hash_name
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_items_game_hash 
                ON items(game_id, market_hash_name)
            ''')
            
            # Index on price_history table for lookups by item_id and timestamp
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_price_history_item_timestamp 
                ON price_history(item_id, timestamp)
            ''')
            
            # Index on price_history table for timestamp-based queries (for data retention)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_price_history_timestamp 
                ON price_history(timestamp)
            ''')
            
            # Index on items table for last_updated queries (for freshness checks)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_items_last_updated 
                ON items(last_updated)
            ''')
            
            conn.commit()
            logging.info("Database initialized with tables and indexes")
    
    def add_indexes_to_existing_db(self):
        """Add indexes to existing database (safe to call multiple times)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create indexes if they don't exist
                indexes = [
                    ('idx_items_game_hash', 'items(game_id, market_hash_name)'),
                    ('idx_price_history_item_timestamp', 'price_history(item_id, timestamp)'),
                    ('idx_price_history_timestamp', 'price_history(timestamp)'),
                    ('idx_items_last_updated', 'items(last_updated)')
                ]
                
                for index_name, index_definition in indexes:
                    try:
                        cursor.execute(f'''
                            CREATE INDEX IF NOT EXISTS {index_name} 
                            ON {index_definition}
                        ''')
                        logging.info(f"Created/verified index: {index_name}")
                    except sqlite3.Error as e:
                        logging.warning(f"Could not create index {index_name}: {e}")
                
                conn.commit()
                logging.info("Indexes added/verified successfully")
        except Exception as e:
            logging.error(f"Error adding indexes: {e}")

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

    def check_rate_limit(self, game_id, operation_type='price_history'):
        """
        Check if we can make a request for the specified game and operation type
        
        Args:
            game_id: Game ID to check
            operation_type: 'listings' or 'price_history' (default: 'price_history')
        """
        # Check overall minute limit first (safety check)
        if not self.rate_limiters[game_id]['minute'].can_make_request():
            wait_time = self.rate_limiters[game_id]['minute'].get_wait_time()
            if wait_time > 0:
                logging.warning(f"[{threading.current_thread().name}] Overall rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
            else:
                # If wait_time is 0, we're likely in a 429 retry period - wait a bit anyway
                logging.debug(f"[{threading.current_thread().name}] Rate limit check failed but wait time is 0, waiting 1 second")
                time.sleep(1)
            return False
        
        # Check operation-specific limit
        if operation_type == 'listings':
            if not self.rate_limiters[game_id]['listings'].can_make_request():
                wait_time = self.rate_limiters[game_id]['listings'].get_wait_time()
                if wait_time > 0:
                    logging.debug(f"[{threading.current_thread().name}] Listings rate limit reached, waiting {wait_time:.2f} seconds")
                    time.sleep(wait_time)
                else:
                    logging.debug(f"[{threading.current_thread().name}] Listings rate limit check failed, waiting 1 second")
                    time.sleep(1)
                return False
        else:  # price_history
            if not self.rate_limiters[game_id]['price_history'].can_make_request():
                wait_time = self.rate_limiters[game_id]['price_history'].get_wait_time()
                if wait_time > 0:
                    logging.debug(f"[{threading.current_thread().name}] Price history rate limit reached, waiting {wait_time:.2f} seconds")
                    time.sleep(wait_time)
                else:
                    logging.debug(f"[{threading.current_thread().name}] Price history rate limit check failed, waiting 1 second")
                    time.sleep(1)
                return False
        
        # Check day limit
        if not self.rate_limiters[game_id]['day'].can_make_request():
            wait_time = self.rate_limiters[game_id]['day'].get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Daily rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return False
            
        return True

    def fetch_market_listings(self, game_id, queue_callback=None):
        """
        Fetch market listings for a specific game with pagination and retry logic
        
        Args:
            game_id: Game ID to fetch listings for
            queue_callback: Optional callback function(item) to call for each item found.
                          If provided, items are queued incrementally as they're fetched.
                          If None, all items are returned at once.
        
        Returns:
            List of all fetched items (if queue_callback is None) or count of items queued
        """
        all_results = []
        items_queued = 0
        start = 0
        count = 100  # Steam's maximum per page
        max_retries = 3
        retry_delay = 5

        while True:
            for retry in range(max_retries):
                try:
                    # Use listings-specific rate limiter
                    if not self.check_rate_limit(game_id, operation_type='listings'):
                        wait_time = self.rate_limiters[game_id]['listings'].get_wait_time()
                        logging.warning(f"[{threading.current_thread().name}] Listings rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
                        time.sleep(wait_time)
                        continue

                    # Add initial delay before first request (reduced for faster collection)
                    if start == 0:
                        time.sleep(random.uniform(1, 2))

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
                            return all_results if queue_callback is None else items_queued
                        
                        all_results.extend(results)
                        logging.info(f"[{threading.current_thread().name}] Successfully fetched {len(results)} items for game {game_id} (Total: {len(all_results)}/{total_count})")
                        
                        # If callback provided, queue items incrementally so workers can start processing
                        if queue_callback:
                            for item in results:
                                if 'hash_name' in item:
                                    queue_callback(item)
                                    items_queued += 1
                            logging.info(f"[{threading.current_thread().name}] Queued {len(results)} items (Total queued: {items_queued})")
                        
                        # Reduced delay between pages - we have rate limiting in place
                        # This allows faster collection while staying within limits
                        time.sleep(random.uniform(2, 3))
                        
                        # Move to next page
                        start += count
                        if start >= total_count:
                            return all_results if queue_callback is None else items_queued
                        break
                        
                    elif response.status_code == 429:
                        retry_after = int(response.headers.get('Retry-After', 60))
                        self.rate_limiters[game_id]['listings'].handle_429(retry_after)
                        self.rate_limiters[game_id]['minute'].handle_429(retry_after)  # Also update overall limit
                        logging.warning(f"[{threading.current_thread().name}] Rate limit hit for listings {self.games[game_id]}, waiting {retry_after} seconds")
                        time.sleep(retry_after)
                        continue
                    else:
                        logging.error(f"[{threading.current_thread().name}] Failed to fetch listings for game {game_id}: {response.status_code}")
                        if retry < max_retries - 1:
                            time.sleep(retry_delay * (retry + 1))
                            continue
                        return all_results if queue_callback is None else items_queued
                        
                except Exception as e:
                    logging.error(f"[{threading.current_thread().name}] Error fetching market listings: {str(e)}")
                    if retry < max_retries - 1:
                        time.sleep(retry_delay * (retry + 1))
                        continue
                    return all_results if queue_callback is None else items_queued

        return all_results if queue_callback is None else items_queued

    def fetch_price_history(self, game_id, market_hash_name):
        """Fetch price history for a specific item using session-based approach with Akamai cookie handling"""
        # Use price_history-specific rate limiter
        if not self.check_rate_limit(game_id, operation_type='price_history'):
            wait_time = self.rate_limiters[game_id]['price_history'].get_wait_time()
            logging.warning(f"[{threading.current_thread().name}] Price history rate limit reached for {self.games[game_id]}, waiting {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return None

        try:
            logging.info(f"[{threading.current_thread().name}] Fetching price history for {market_hash_name} (Game: {self.games[game_id]})")
            
            # Use a session to maintain cookies across requests
            # This is critical - Steam uses Akamai bot management that requires visiting the page first
            http_session = requests.Session()
            
            # Set cookies properly in session with correct domain
            from requests.cookies import create_cookie
            
            # Required cookies
            sessionid_cookie = create_cookie(
                name='sessionid',
                value=self.steam_cookies['sessionid'],
                domain='steamcommunity.com',
                path='/'
            )
            steamLoginSecure_cookie = create_cookie(
                name='steamLoginSecure',
                value=self.steam_cookies['steamLoginSecure'],
                domain='steamcommunity.com',
                path='/'
            )
            http_session.cookies.set_cookie(sessionid_cookie)
            http_session.cookies.set_cookie(steamLoginSecure_cookie)
            
            # Optional cookies that help establish full session (set if available)
            if self.steam_cookies.get('browserid'):
                browserid_cookie = create_cookie(
                    name='browserid',
                    value=self.steam_cookies['browserid'],
                    domain='steamcommunity.com',
                    path='/'
                )
                http_session.cookies.set_cookie(browserid_cookie)
            
            if self.steam_cookies.get('steamCountry'):
                steamCountry_cookie = create_cookie(
                    name='steamCountry',
                    value=self.steam_cookies['steamCountry'],
                    domain='steamcommunity.com',
                    path='/'
                )
                http_session.cookies.set_cookie(steamCountry_cookie)
            
            if self.steam_cookies.get('webTradeEligibility'):
                webTradeEligibility_cookie = create_cookie(
                    name='webTradeEligibility',
                    value=self.steam_cookies['webTradeEligibility'],
                    domain='steamcommunity.com',
                    path='/'
                )
                http_session.cookies.set_cookie(webTradeEligibility_cookie)
            
            # CRITICAL: Visit Steam community homepage first to establish full session
            # This mimics what happens when you're already logged into Steam in your browser
            homepage_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
            }
            
            homepage_response = http_session.get('https://steamcommunity.com/', headers=homepage_headers, timeout=10)
            time.sleep(0.3)  # Small delay
            
            # CRITICAL: Visit the market listing page to establish session and get Akamai cookies
            # Browsers do this automatically - they load the page, then make the API request
            from urllib.parse import quote
            listing_url = f'https://steamcommunity.com/market/listings/{game_id}/{quote(market_hash_name)}'
            
            listing_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
                'Referer': 'https://steamcommunity.com/',  # Add referer from homepage
            }
            
            listing_response = http_session.get(listing_url, headers=listing_headers, timeout=10)
            
            if listing_response.status_code == 200:
                # Check what cookies Steam set (especially ak_bmsc, browserid, etc.)
                new_cookies = list(http_session.cookies.keys())
                if 'ak_bmsc' in new_cookies:
                    logging.debug(f"[{threading.current_thread().name}] Got ak_bmsc cookie (Akamai bot management)")
                if 'browserid' in new_cookies:
                    logging.debug(f"[{threading.current_thread().name}] Got browserid cookie")
            else:
                logging.warning(f"[{threading.current_thread().name}] Listing page returned {listing_response.status_code}")
            
            # Now make the price history request with the established session
            # CRITICAL: Match browser headers EXACTLY - use text/html Accept header, NOT application/json!
            url = "https://steamcommunity.com/market/pricehistory/"
            params = {
                'appid': game_id,
                'market_hash_name': market_hash_name,
                'currency': 1  # USD
            }
            
            api_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'max-age=0',
                'Connection': 'keep-alive',
                'Referer': listing_url,  # Add Referer header - browser sends this when navigating from listing page
                'Sec-Fetch-Dest': 'document',  # Browser treats it as document navigation, not API
                'Sec-Fetch-Mode': 'navigate',  # Navigation mode, not cors/ajax
                'Sec-Fetch-Site': 'same-origin',  # Same origin since we're navigating from listing page
                'Sec-Fetch-User': '?1',  # User-initiated request
                'Upgrade-Insecure-Requests': '1',
                'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
            }
            
            # Small delay like a browser would have (reduced for faster collection)
            time.sleep(0.3)
            response = http_session.get(url, params=params, headers=api_headers, timeout=10)
            
            if response.status_code == 200:
                # Check content type - might be JSON even with text/html Accept header
                content_type = response.headers.get('Content-Type', '').lower()
                
                try:
                    # Try to parse as JSON first (Steam usually returns JSON even with text/html Accept)
                    data = response.json()
                    
                    if 'prices' in data and len(data['prices']) > 0:
                        logging.info(f"[{threading.current_thread().name}] Successfully fetched {len(data['prices'])} price history entries for {market_hash_name}")
                        return data
                    elif 'prices' in data and len(data['prices']) == 0:
                        logging.warning(f"[{threading.current_thread().name}] Response 200 but prices array is empty for {market_hash_name}")
                        return {'prices': []}
                    else:
                        logging.warning(f"[{threading.current_thread().name}] Response 200 but unexpected format: {list(data.keys())}")
                        return data
                        
                except ValueError as e:
                    # Not JSON - might be HTML or other format
                    logging.error(f"[{threading.current_thread().name}] Response is not JSON. Content-Type: {content_type}")
                    logging.error(f"[{threading.current_thread().name}] First 500 chars: {response.text[:500]}")
                    return None
                    
            elif response.status_code == 400:
                # Steam returns 400 with [] for items with no history or invalid requests
                response_text = response.text.strip()
                if response_text == '[]':
                    # 400 with [] typically means:
                    # - Account restrictions (no purchase in last year, etc.)
                    # - Item has no price history available
                    # - Invalid item name
                    # These are permanent conditions, not transient errors
                    logging.warning(f"[{threading.current_thread().name}] Steam returned 400 with empty array for {market_hash_name} - no price history or account restrictions (skipping retries)")
                    # Return a special marker to indicate this is a permanent failure
                    return {'prices': [], '_permanent_failure': True}
                else:
                    logging.error(f"[{threading.current_thread().name}] Steam returned 400: {response_text[:200]}")
                    return None
                    
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                self.rate_limiters[game_id]['price_history'].handle_429(retry_after)
                self.rate_limiters[game_id]['minute'].handle_429(retry_after)  # Also update overall limit
                logging.warning(f"[{threading.current_thread().name}] Rate limit hit for price history {self.games[game_id]}, waiting {retry_after} seconds")
                time.sleep(retry_after)
                return None
            else:
                logging.error(f"[{threading.current_thread().name}] Failed to fetch price history for {market_hash_name}: {response.status_code}")
                logging.error(f"[{threading.current_thread().name}] Response: {response.text[:200]}")
                return None
                
        except requests.exceptions.Timeout:
            logging.error(f"[{threading.current_thread().name}] Request to Steam timed out for {market_hash_name}")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"[{threading.current_thread().name}] Network error fetching price history: {str(e)}")
            return None
        except Exception as e:
            logging.error(f"[{threading.current_thread().name}] Error fetching price history: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
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
    
    def get_item_last_updated(self, market_hash_name, game_id):
        """Get the last_updated timestamp for an item"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT last_updated 
                    FROM items 
                    WHERE market_hash_name = ? AND game_id = ?
                ''', (market_hash_name, game_id))
                result = cursor.fetchone()
                if result and result[0]:
                    # Parse timestamp string to datetime
                    try:
                        return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
                    except ValueError:
                        try:
                            return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            return None
                return None
        except Exception as e:
            logging.error(f"Error getting item last_updated: {e}")
            return None
    
    def should_update_price_history(self, market_hash_name, game_id, update_interval_hours=12):
        """Check if price history should be updated based on last_updated timestamp"""
        last_updated = self.get_item_last_updated(market_hash_name, game_id)
        
        # If item doesn't exist in database, we should fetch it
        if last_updated is None:
            return True
        
        # Check if data is older than update interval
        time_since_update = datetime.now() - last_updated
        hours_since_update = time_since_update.total_seconds() / 3600
        
        if hours_since_update >= update_interval_hours:
            logging.debug(f"Item {market_hash_name} last updated {hours_since_update:.1f} hours ago, needs update")
            return True
        
        logging.debug(f"Item {market_hash_name} last updated {hours_since_update:.1f} hours ago, skipping (fresh)")
        return False

    def parse_steam_timestamp(self, timestamp_str):
        """Parse Steam timestamp format to datetime object"""
        try:
            import re
            # Steam format: "Dec 06 2018 01: +0"
            clean_timestamp = re.sub(r'\s+\+\d+$', '', timestamp_str).strip()
            parts = re.match(r'(\w+)\s+(\d+)\s+(\d+)\s+(\d+):', clean_timestamp)
            if parts:
                month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                month = month_names.index(parts.group(1)) + 1
                day = int(parts.group(2))
                year = int(parts.group(3))
                hour = int(parts.group(4))
                return datetime(year, month, day, hour)
        except (ValueError, AttributeError, IndexError):
            pass
        return None

    def store_price_history(self, item_id, price_data):
        """
        Store price history data in database using batch inserts for better performance
        
        Returns:
            int: Number of entries added to database (0 if no data or error)
        """
        if not price_data or 'prices' not in price_data:
            return 0

        # Prepare batch data for bulk insert
        batch_with_normalized = []
        batch_without_normalized = []
        
        for entry in price_data['prices']:
            try:
                timestamp_str = entry[0]
                price = float(entry[1])
                volume = int(entry[2])
                
                # Basic data validation
                if price < 0 or volume < 0:
                    logging.warning(f"Skipping invalid data: price={price}, volume={volume}")
                    continue
                
                # Parse normalized timestamp for ML optimization
                normalized_timestamp = None
                dt = self.parse_steam_timestamp(timestamp_str)
                if dt:
                    normalized_timestamp = dt.isoformat()
                
                if normalized_timestamp:
                    batch_with_normalized.append((item_id, timestamp_str, normalized_timestamp, price, volume))
                else:
                    batch_without_normalized.append((item_id, timestamp_str, price, volume))
            except (ValueError, TypeError, IndexError) as e:
                logging.warning(f"Error parsing price history entry: {str(e)}, entry: {entry}")
                continue
        
        # Batch insert with normalized timestamps
        entries_added = 0
        with sqlite3.connect(self.db_path) as conn:
            # Apply optimizations for this connection
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            
            cursor = conn.cursor()
            
            try:
                if batch_with_normalized:
                    cursor.executemany('''
                        INSERT OR IGNORE INTO price_history 
                        (item_id, timestamp, timestamp_normalized, price, volume)
                        VALUES (?, ?, ?, ?, ?)
                    ''', batch_with_normalized)
                    entries_added += cursor.rowcount
                
                if batch_without_normalized:
                    cursor.executemany('''
                        INSERT OR IGNORE INTO price_history 
                        (item_id, timestamp, price, volume)
                        VALUES (?, ?, ?, ?)
                    ''', batch_without_normalized)
                    entries_added += cursor.rowcount
                
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                logging.error(f"Error in batch insert: {str(e)}")
                # Fallback to individual inserts if batch fails
                entries_added = self._store_price_history_individual(item_id, price_data)
        
        if entries_added > 0:
            logging.info(f"[{threading.current_thread().name}] Stored {entries_added} new price history entries in database (batch insert)")
        
        return entries_added
    
    def _store_price_history_individual(self, item_id, price_data):
        """Fallback method for individual inserts if batch insert fails"""
        entries_added = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for entry in price_data['prices']:
                try:
                    timestamp_str = entry[0]
                    price = float(entry[1])
                    volume = int(entry[2])
                    
                    if price < 0 or volume < 0:
                        continue
                    
                    normalized_timestamp = None
                    dt = self.parse_steam_timestamp(timestamp_str)
                    if dt:
                        normalized_timestamp = dt.isoformat()
                    
                    if normalized_timestamp:
                        cursor.execute('''
                            INSERT OR IGNORE INTO price_history 
                            (item_id, timestamp, timestamp_normalized, price, volume)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (item_id, timestamp_str, normalized_timestamp, price, volume))
                    else:
                        cursor.execute('''
                            INSERT OR IGNORE INTO price_history 
                            (item_id, timestamp, price, volume)
                            VALUES (?, ?, ?, ?)
                        ''', (item_id, timestamp_str, price, volume))
                    
                    if cursor.rowcount > 0:
                        entries_added += 1
                except (sqlite3.Error, ValueError, TypeError, IndexError) as e:
                    logging.error(f"Error storing price history entry: {str(e)}")
                    continue
            
            conn.commit()
        return entries_added

    def calculate_dynamic_sleep(self, thread_name, game_id):
        """Calculate dynamic sleep time to maintain constant stream while respecting rate limits"""
        base_sleep = self.worker_sleep_times.get(thread_name, 7.5)
        # Use price_history rate limiter for worker sleep calculation
        requests_in_window = self.rate_limiters[game_id]['price_history'].get_requests_in_window()
        max_requests = self.rate_limiters[game_id]['price_history'].max_requests
        
        # Calculate how much capacity we have left
        capacity_remaining = max_requests - requests_in_window
        
        # If we're getting close to the limit (within 2 requests), slow down significantly
        if capacity_remaining <= 2:
            # Wait until oldest request expires
            wait_time = self.rate_limiters[game_id]['price_history'].get_wait_time()
            if wait_time > 0:
                logging.debug(f"[{thread_name}] Price history rate limit approaching, waiting {wait_time:.1f}s")
                return wait_time + 1  # Add 1 second buffer
            return base_sleep * 2  # Double sleep time as safety
        
        # If we have moderate capacity (3-4 requests left), slightly increase sleep
        elif capacity_remaining <= 4:
            return base_sleep * 1.2
        
        # If we have good capacity (5+ requests left), use base sleep with small jitter
        # Add small random jitter (0.5s) to prevent synchronization between workers
        jitter = random.uniform(-0.3, 0.3)
        return max(5, base_sleep + jitter)  # Minimum 5 seconds between requests

    def _check_pause(self):
        """Check if pause file exists and pause if needed."""
        if self.pause_file and os.path.exists(self.pause_file):
            if not hasattr(self, '_paused_logged'):
                logging.info("=" * 70)
                logging.info("PAUSE DETECTED: Collection paused")
                logging.info(f"Delete '{self.pause_file}' to resume collection")
                logging.info("=" * 70)
                self._paused_logged = True
            
            # Wait until pause file is removed
            while os.path.exists(self.pause_file) and not self.stop_event.is_set():
                time.sleep(1)
            
            if hasattr(self, '_paused_logged'):
                logging.info("=" * 70)
                logging.info("RESUMING: Collection resumed")
                logging.info("=" * 70)
                delattr(self, '_paused_logged')
            
            return True
        return False
    
    def worker(self):
        """Worker thread that processes items from the queue"""
        thread_name = threading.current_thread().name
        logging.info(f"[{thread_name}] Worker thread started")
        
        while not self.stop_event.is_set():
            try:
                # Check for pause
                if self._check_pause():
                    continue
                
                # Use a shorter timeout to be more responsive to stop events
                priority, item = self.item_queue.get(timeout=0.1)
                if item is None:
                    continue

                game_id, market_hash_name = item
                queue_size = self.item_queue.qsize()
                logging.info(f"[{thread_name}] Processing: {market_hash_name[:50]}... (Game: {self.games[game_id]}, Priority: {'NEW' if priority == ItemPriority.NEW_ITEM else 'OLD'}, Queue: {queue_size} remaining)")
                
                # Check if we need to update this item (incremental updates)
                if not self.should_update_price_history(market_hash_name, game_id, self.update_interval_hours):
                    logging.info(f"[{thread_name}] Skipping {market_hash_name} - data is fresh (updated within {self.update_interval_hours} hours)")
                    self.item_queue.task_done()
                    continue
                
                # Implement exponential backoff for rate limits
                max_retries = 3
                retry_delay = 1
                
                price_history = None
                for attempt in range(max_retries):
                    # Check stop event between retries for graceful shutdown
                    if self.stop_event.is_set():
                        logging.info(f"[{thread_name}] Stop event set, exiting worker")
                        self.item_queue.task_done()
                        return
                    
                    if self.check_rate_limit(game_id, operation_type='price_history'):
                        price_history = self.fetch_price_history(game_id, market_hash_name)
                        if price_history:
                            # Check if this is a permanent failure (400 with empty array)
                            if price_history.get('_permanent_failure'):
                                # Don't retry - this is a permanent condition (account restrictions, no history, etc.)
                                logging.warning(f"[{thread_name}] Skipping {market_hash_name} - permanent failure (no price history available or account restrictions)")
                                break
                            
                            # Check if we actually got price data (not just empty array)
                            has_data = price_history.get('prices') and len(price_history.get('prices', [])) > 0
                            
                            if has_data:
                                item_id = self.store_item(market_hash_name, game_id)
                                entries_added = self.store_price_history(item_id, price_history)
                                self.update_item_freshness(market_hash_name, game_id, is_new=False)
                                
                                # Log success with data point count
                                data_points = len(price_history.get('prices', []))
                                logging.info(f"[{thread_name}] [SUCCESS] Processed {market_hash_name} - {data_points} data points fetched, {entries_added} new entries stored")
                                break
                            else:
                                # Got response but no actual price data (unexpected case)
                                logging.warning(f"[{thread_name}] No price history data available for {market_hash_name} (empty response from Steam)")
                                if attempt < max_retries - 1:
                                    logging.warning(f"[{thread_name}] Retrying {market_hash_name} (attempt {attempt + 1}/{max_retries})...")
                        else:
                            # fetch_price_history returned None - log the attempt
                            if attempt < max_retries - 1:
                                logging.warning(f"[{thread_name}] Failed to fetch price history for {market_hash_name} (attempt {attempt + 1}/{max_retries}), retrying...")
                    else:
                        if attempt < max_retries - 1:
                            logging.debug(f"[{thread_name}] Rate limit reached, waiting before retry {attempt + 1}/{max_retries} for {market_hash_name}")
                            # Check stop event during backoff
                            for _ in range(int(retry_delay)):
                                if self.stop_event.is_set():
                                    logging.info(f"[{thread_name}] Stop event set during backoff, exiting worker")
                                    self.item_queue.task_done()
                                    return
                                time.sleep(1)
                            retry_delay *= 2  # Exponential backoff
                
                # Log final result if all retries failed
                if not price_history:
                    logging.error(f"[{thread_name}] [FAILED] Failed to process {market_hash_name} for game {game_id} after {max_retries} attempts")
                
                self.item_queue.task_done()
                
                # Dynamic sleep based on rate limit status
                # Sleep in increments to check stop event
                sleep_time = self.calculate_dynamic_sleep(thread_name, game_id)
                logging.debug(f"[{thread_name}] Sleeping for {sleep_time:.2f} seconds")
                
                # Sleep in 1-second increments to be responsive to stop events
                sleep_remaining = sleep_time
                while sleep_remaining > 0 and not self.stop_event.is_set():
                    sleep_chunk = min(1.0, sleep_remaining)
                    time.sleep(sleep_chunk)
                    sleep_remaining -= sleep_chunk
                
                if self.stop_event.is_set():
                    logging.info(f"[{thread_name}] Stop event set during sleep, exiting worker")
                    break
                
            except Empty:
                # Check stop event when queue is empty
                if self.stop_event.is_set():
                    logging.info(f"[{thread_name}] Stop event set, exiting worker")
                    break
                # Log periodically when waiting for items (every 10 seconds of waiting)
                with self._empty_log_lock:
                    if thread_name not in self._last_empty_log:
                        self._last_empty_log[thread_name] = time.time()
                    
                    current_time = time.time()
                    if current_time - self._last_empty_log[thread_name] >= 10:
                        queue_size = self.item_queue.qsize()
                        logging.info(f"[{thread_name}] Waiting for items... (Queue size: {queue_size})")
                        self._last_empty_log[thread_name] = current_time
                continue
            except Exception as e:
                logging.error(f"[{thread_name}] Error in worker thread: {str(e)}")
                # Check stop event after error
                if self.stop_event.is_set():
                    logging.info(f"[{thread_name}] Stop event set after error, exiting worker")
                    break
        
        logging.info(f"[{thread_name}] Worker thread stopping")

    def validate_cookies(self, game_id='730'):
        """
        Quick validation of Steam cookies by attempting to fetch price history for a common item.
        Returns True if cookies appear valid, False otherwise.
        """
        try:
            # Use a common CS2 item that should have price history
            test_item = 'Danger Zone Case'
            logging.info(f"Validating Steam cookies by testing price history access for '{test_item}'...")
            
            price_history = self.fetch_price_history(game_id, test_item)
            
            if price_history and price_history.get('prices') and len(price_history.get('prices', [])) > 0:
                data_points = len(price_history.get('prices', []))
                logging.info(f"[OK] Cookie validation successful! Retrieved {data_points} price history entries.")
                return True
            elif price_history and price_history.get('_permanent_failure'):
                logging.warning(f"[WARNING] Cookie validation: Steam returned 400 with empty array.")
                logging.warning(f"This may indicate account restrictions (no purchase in last year, etc.).")
                logging.warning(f"Many items may return 400 errors. Consider updating cookies or checking account status.")
                return False
            else:
                logging.warning(f"[WARNING] Cookie validation: No price history data retrieved.")
                logging.warning(f"Cookies may be invalid or account has restrictions. Consider running 'python scripts/test_cookies.py' to verify.")
                return False
        except Exception as e:
            logging.error(f"[ERROR] Cookie validation failed: {str(e)}")
            logging.warning(f"Consider running 'python scripts/test_cookies.py' to verify your cookies.")
            return False

    def start_collection(self, num_workers=3):  # Default 3 workers for better rate limit utilization
        """Start the collection process with multiple worker threads"""
        logging.info(f"Starting collection with {num_workers} worker threads")
        
        # Validate cookies before starting collection
        if not self.validate_cookies():
            logging.warning("=" * 70)
            logging.warning("WARNING: Cookie validation failed or returned no data!")
            logging.warning("You may experience many 400 errors during collection.")
            logging.warning("Run 'python scripts/test_cookies.py' to verify your cookies.")
            logging.warning("=" * 70)
        else:
            logging.info("Cookie validation passed - ready to collect data")
        
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

        # Main collection loop with scheduled listings fetch
        # Fetch listings on a fixed schedule (every hour) independent of queue status
        # This ensures workers always have items to process and better rate limit balance
        listings_fetch_interval = 3600  # 1 hour in seconds
        last_listings_fetch = {}
        
        try:
            while not self.stop_event.is_set():
                # Check for pause in main loop
                if self._check_pause():
                    time.sleep(1)
                    continue
                
                current_time = time.time()
                
                # Check if it's time to fetch listings for each game
                for game_id in self.games:
                    # Initialize last fetch time if not set
                    if game_id not in last_listings_fetch:
                        last_listings_fetch[game_id] = 0
                    
                    # Fetch listings if interval has passed
                    time_since_last_fetch = current_time - last_listings_fetch[game_id]
                    if time_since_last_fetch >= listings_fetch_interval:
                        logging.info(f"Starting scheduled listings fetch for game {game_id} ({self.games[game_id]})")
                        
                        # Check rate limit before fetching listings
                        if self.check_rate_limit(game_id, operation_type='listings'):
                            try:
                                # Define callback to queue items incrementally as they're fetched
                                # This allows workers to start processing immediately
                                def queue_item(item):
                                    market_hash_name = item['hash_name']
                                    priority = self.get_item_freshness(market_hash_name, game_id)
                                    self.item_queue.put((priority, (game_id, market_hash_name)))
                                
                                # Fetch and queue items incrementally
                                items_added = self.fetch_market_listings(game_id, queue_callback=queue_item)
                                
                                logging.info(f"[MainThread] Completed listings fetch: {items_added} items queued for game {game_id}")
                                last_listings_fetch[game_id] = current_time
                            except Exception as e:
                                logging.error(f"Error fetching listings for {game_id}: {str(e)}")
                                # Retry in 5 minutes if failed
                                last_listings_fetch[game_id] = current_time - listings_fetch_interval + 300
                        else:
                            logging.warning(f"Listings rate limit reached, will retry in 1 minute for game {game_id}")
                            # Retry in 1 minute
                            last_listings_fetch[game_id] = current_time - listings_fetch_interval + 60
                
                # Sleep for a short period before checking again
                # This allows workers to process queue while main thread waits
                # Sleep in 1-second increments for responsive shutdown
                sleep_interval = 60  # Check every minute
                for _ in range(sleep_interval):
                    if self.stop_event.is_set():
                        break
                    time.sleep(1)  # Sleep in 1-second increments for responsive shutdown
        except KeyboardInterrupt:
            logging.info("Keyboard interrupt received, initiating graceful shutdown...")
            self.stop_event.set()
            
            # Wait for all threads to finish (with timeout)
            logging.info("Waiting for worker threads to finish current operations...")
            for thread in threads:
                thread.join(timeout=30)  # Wait up to 30 seconds per thread
                if thread.is_alive():
                    logging.warning(f"Worker thread {thread.name} did not stop within timeout")
                else:
                    logging.info(f"Worker thread {thread.name} stopped gracefully")
            
            # Wait for queue to be processed (with timeout)
            if not self.item_queue.empty():
                logging.info(f"Queue has {self.item_queue.qsize()} items remaining")
                logging.info("Waiting up to 60 seconds for queue to be processed...")
                start_wait = time.time()
                while not self.item_queue.empty() and (time.time() - start_wait) < 60:
                    time.sleep(1)
                
                if not self.item_queue.empty():
                    logging.warning(f"Queue still has {self.item_queue.qsize()} items when shutting down")
                else:
                    logging.info("Queue processed successfully")
            
            logging.info("Shutdown complete")

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
                                self.add_to_queue(game_id, market_hash_name, priority=ItemPriority.NEW_ITEM)
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

    def add_to_queue(self, game_id, market_hash_name, priority=None):
        """Add an item to the queue with priority"""
        # If priority not provided, get it from freshness status (same as start_collection)
        if priority is None:
            priority = self.get_item_freshness(market_hash_name, game_id)
        
        # Use standard queue format: (priority, (game_id, market_hash_name))
        # This matches the format used in start_collection() and expected by worker()
        self.item_queue.put((priority, (game_id, market_hash_name)))

if __name__ == "__main__":
    collector = SteamMarketCollector()
    collector.start_collection() 