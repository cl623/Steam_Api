from typing import Dict, List, Set, Optional
import time
import os
from dataclasses import dataclass
from enum import Enum
import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
import json
from queue import Queue, PriorityQueue
from threading import Lock, Thread, Event
import sqlite3
import csv
import csv

class Game(Enum):
    MAPLESTORY = "216150"
    CS2 = "730"

@dataclass
class BatchConfig:
    total_batch_size: int = 100
    items_per_game: int = 30  # Reduced from 50 to avoid rate limiting
    page_size: int = 10
    pages_per_game: int = 3   # Reduced from 5 to avoid rate limiting
    cooldown_minutes: int = 5
    min_delay_between_requests: float = 3.0  # Increased from 2.0
    max_retries: int = 3

@dataclass
class MarketItem:
    """Represents a Steam market item with its data"""
    hash_name: str
    name: str
    game: Game
    sell_price: float
    sell_listings: int
    timestamp: float
    
    def __lt__(self, other):
        """For priority queue ordering - lower prices first"""
        return self.sell_price < other.sell_price
    
    def __repr__(self):
        return f"MarketItem({self.name}, ${self.sell_price:.2f}, {self.sell_listings} listings)"

@dataclass
class PriceHistoryEntry:
    """Represents a price history entry for an item"""
    item_hash_name: str
    game_id: str
    timestamp: float
    price: float
    volume: int
    
    def __repr__(self):
        return f"PriceHistory({self.item_hash_name}, ${self.price:.2f}, vol:{self.volume})"

class SteamAPIError(Exception):
    """Custom exception for Steam API errors"""
    pass

class DatabaseManager:
    """Manages SQLite database operations for price history data"""
    
    def __init__(self, db_path: str = "steam_market.db"):
        self.db_path = db_path
        self.csv_path = "steam_market_summary.csv"
        self.init_database()
        self.init_csv()
    
    def init_database(self):
        """Initialize the database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Items table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_hash_name TEXT NOT NULL,
                    game_id TEXT NOT NULL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(market_hash_name, game_id)
                )
            """)
            
            # Price history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    FOREIGN KEY (item_id) REFERENCES items (id),
                    UNIQUE(item_id, timestamp, price, volume)
                )
            """)
            
            conn.commit()
    
    def init_csv(self):
        """Initialize the CSV file with headers"""
        try:
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Item Name', 'Game ID', 'Data Points', 'Current Price', 'Last Updated'])
            logger.info(f"CSV file initialized: {self.csv_path}")
        except Exception as e:
            logger.error(f"Failed to initialize CSV file: {str(e)}")
    
    def insert_or_update_item(self, market_hash_name: str, game_id: str) -> int:
        """Insert or update an item and return its ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Try to insert, if exists update last_updated
            cursor.execute("""
                INSERT OR REPLACE INTO items (market_hash_name, game_id, last_updated)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (market_hash_name, game_id))
            
            # Get the item ID
            cursor.execute("""
                SELECT id FROM items WHERE market_hash_name = ? AND game_id = ?
            """, (market_hash_name, game_id))
            
            return cursor.fetchone()[0]
    
    def insert_price_history(self, item_id: int, timestamp: float, price: float, volume: int):
        """Insert a price history entry"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR IGNORE INTO price_history (item_id, timestamp, price, volume)
                VALUES (?, ?, ?, ?)
            """, (item_id, timestamp, price, volume))
            
            conn.commit()
    
    def should_fetch_price_history(self, item_name: str, game_id: str) -> bool:
        """Check if we should fetch price history for this item based on database freshness"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if item exists and when it was last updated
                cursor.execute("""
                    SELECT i.last_updated, COUNT(ph.id) as data_points
                    FROM items i
                    LEFT JOIN price_history ph ON i.id = ph.item_id
                    WHERE i.market_hash_name = ? AND i.game_id = ?
                    GROUP BY i.id
                """, (item_name, game_id))
                
                result = cursor.fetchone()
                
                if not result:
                    logger.info(f"🆕 NEW ITEM: {item_name} ({game_id}) - will fetch")
                    return True  # New item, fetch it
                
                last_updated, data_points = result
                
                # Skip if updated recently (e.g., within 24 hours) and has data
                if last_updated and data_points > 0:
                    from datetime import datetime, timedelta
                    try:
                        # Parse the last_updated timestamp
                        last_update = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                        if datetime.now() - last_update < timedelta(hours=24):
                            logger.info(f"⏭️ SKIPPED: {item_name} ({game_id}) - updated {last_update.strftime('%Y-%m-%d %H:%M')} ({data_points} data points)")
                            return False
                    except ValueError:
                        # If timestamp parsing fails, fetch anyway
                        logger.warning(f"⚠️ TIMESTAMP PARSE ERROR: {item_name} ({game_id}) - will fetch")
                        return True
                
                logger.info(f"🔄 STALE DATA: {item_name} ({game_id}) - last updated {last_updated}, {data_points} data points - will fetch")
                return True
                
        except Exception as e:
            logger.error(f"❌ DATABASE CHECK ERROR: {item_name} ({game_id}): {str(e)}")
            return True  # On error, fetch anyway
    
    def mark_item_recently_processed(self, item_name: str, game_id: str):
        """Mark an item as recently processed by updating its last_updated timestamp"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Update the last_updated timestamp for this item
                cursor.execute("""
                    UPDATE items 
                    SET last_updated = CURRENT_TIMESTAMP
                    WHERE market_hash_name = ? AND game_id = ?
                """, (item_name, game_id))
                
                conn.commit()
                logger.debug(f"📝 MARKED RECENT: {item_name} ({game_id})")
                
        except Exception as e:
            logger.error(f"❌ MARK RECENT ERROR: {item_name} ({game_id}): {str(e)}")
    
    def mark_all_existing_items_recently_processed(self):
        """Mark all existing items in the database as recently processed"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Update all items to have current timestamp
                cursor.execute("""
                    UPDATE items 
                    SET last_updated = CURRENT_TIMESTAMP
                    WHERE last_updated IS NOT NULL
                """)
                
                updated_count = cursor.rowcount
                conn.commit()
                
                logger.info(f"📝 MARKED {updated_count} EXISTING ITEMS as recently processed")
                
        except Exception as e:
            logger.error(f"❌ MARK ALL RECENT ERROR: {str(e)}")
    
    def update_csv_summary(self, item_name: str, game_id: str, data_points: int, current_price: float):
        """Update the CSV file with item summary data"""
        try:
            # Read existing data
            rows = []
            try:
                with open(self.csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.reader(csvfile)
                    header = next(reader)  # Skip header
                    rows = list(reader)
            except FileNotFoundError:
                # File doesn't exist, create it with header
                self.init_csv()
                rows = []
            
            # Check if item already exists in CSV
            item_found = False
            for i, row in enumerate(rows):
                if row[0] == item_name and row[1] == game_id:
                    # Update existing row
                    rows[i] = [item_name, game_id, str(data_points), f"${current_price:.2f}", time.strftime('%Y-%m-%d %H:%M:%S')]
                    item_found = True
                    break
            
            if not item_found:
                # Add new row
                rows.append([item_name, game_id, str(data_points), f"${current_price:.2f}", time.strftime('%Y-%m-%d %H:%M:%S')])
            
            # Write back to CSV
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Item Name', 'Game ID', 'Data Points', 'Current Price', 'Last Updated'])
                writer.writerows(rows)
                
            logger.info(f"📄 CSV UPDATED: {item_name} - {data_points} data points, ${current_price:.2f}")
            
        except Exception as e:
            logger.error(f"Failed to update CSV summary for {item_name}: {str(e)}")

class Worker(Thread):
    """Worker thread to process price history data for a specific game"""
    
    def __init__(self, game: Game, item_queue: Queue, session: requests.Session, 
                 database: DatabaseManager, stop_event: Event):
        super().__init__()
        self.game = game
        self.item_queue = item_queue
        self.session = session
        self.database = database
        self.stop_event = stop_event
        self.processed_count = 0
        self.error_count = 0
        
        # Price history processing statistics
        self.price_data_success_count = 0
        self.price_data_failed_count = 0
        self.rate_limited_count = 0
        self.no_price_data_count = 0
        
        # Rate limiting for price history requests
        self.last_request_time = 0
        self.min_delay = 5.0  # 5 seconds between price history requests (increased due to rate limiting)
        
        # Progress reporting
        self.last_summary_time = time.time()
        self.summary_interval = 60  # Log summary every 60 seconds
        
    def run(self):
        """Main worker loop"""
        logger.info(f"Worker started for {self.game.name}")
        
        while not self.stop_event.is_set():
            try:
                # Get item from queue with timeout
                try:
                    item = self.item_queue.get(timeout=1.0)
                except:
                    continue  # No items in queue, continue loop
                
                # Process the item
                self.process_item(item)
                self.processed_count += 1
                
                # Rate limiting
                self._rate_limit()
                
                # Periodic progress summary
                current_time = time.time()
                if current_time - self.last_summary_time >= self.summary_interval:
                    self._log_progress_summary()
                    self.last_summary_time = current_time
                
            except Exception as e:
                logger.error(f"Worker error for {self.game.name}: {str(e)}")
                self.error_count += 1
                time.sleep(1)  # Brief pause on error
        
        logger.info(f"Worker stopped for {self.game.name}. Processed: {self.processed_count}, Errors: {self.error_count}")
        logger.info(f"Price history summary for {self.game.name}:")
        logger.info(f"  - Successfully fetched price data: {self.price_data_success_count}")
        logger.info(f"  - Failed to fetch price data: {self.price_data_failed_count}")
        logger.info(f"  - Rate limited requests: {self.rate_limited_count}")
        logger.info(f"  - No price data available: {self.no_price_data_count}")
    
    def process_item(self, item: MarketItem):
        """Process a single item to get its price history data"""
        try:
            logger.debug(f"Processing price history for {item.name} ({self.game.name})")
            
            # Check if we should fetch this item based on database freshness
            if not self.database.should_fetch_price_history(item.hash_name, self.game.value):
                # Item was recently processed, skip it
                return
            
            # Get full price history data from Steam API
            price_history_data = self._fetch_price_history(item.hash_name)
            
            if price_history_data and price_history_data.get('prices'):
                # Store in database
                item_id = self.database.insert_or_update_item(item.hash_name, self.game.value)
                
                # Store all price history entries
                entries_stored = 0
                for entry in price_history_data['prices']:
                    # Steam API returns price history as [timestamp, price, volume]
                    timestamp_str, price, volume = entry
                    
                    # Parse the timestamp string to Unix timestamp
                    try:
                        # Handle Steam's timestamp format like "Nov 12 2014 01: +0"
                        # Convert to Unix timestamp
                        from datetime import datetime
                        import re
                        
                        # Parse the timestamp string
                        # Format: "Nov 12 2014 01: +0" or similar
                        # Extract month, day, year, hour
                        match = re.match(r'(\w+)\s+(\d+)\s+(\d+)\s+(\d+):\s*([+-]\d+)', timestamp_str)
                        if match:
                            month_str, day, year, hour, timezone = match.groups()
                            
                            # Convert month name to number
                            month_map = {
                                'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                                'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                            }
                            month = month_map.get(month_str, 1)
                            
                            # Create datetime object and convert to Unix timestamp
                            dt = datetime(int(year), month, int(day), int(hour))
                            unix_timestamp = dt.timestamp()
                        else:
                            # Fallback: try to parse as Unix timestamp if it's numeric
                            unix_timestamp = float(timestamp_str)
                            
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Could not parse timestamp '{timestamp_str}' for {item.name}, skipping entry")
                        continue
                    
                    self.database.insert_price_history(
                        item_id, unix_timestamp, float(price), int(volume)
                    )
                    entries_stored += 1
                
                self.price_data_success_count += 1
                logger.info(f"✅ SUCCESS: Fetched and stored {entries_stored} price history entries for {item.name} ({self.game.name})")
                
                # Mark item as recently processed
                self.database.mark_item_recently_processed(item.hash_name, self.game.value)
                
                # Update CSV summary with the data
                current_price = item.sell_price  # Use the current price from the item
                self.database.update_csv_summary(item.name, self.game.value, entries_stored, current_price)
            else:
                self.no_price_data_count += 1
                logger.warning(f"⚠ FAILED: No price history data available for {item.name} ({self.game.name})")
                
        except SteamAPIError as e:
            if "Rate limited" in str(e):
                self.rate_limited_count += 1
                logger.warning(f"🔄 RATE LIMITED: {item.name} ({self.game.name}) - will retry")
            else:
                self.price_data_failed_count += 1
                logger.error(f"❌ STEAM API ERROR: Failed to fetch price history for {item.name} ({self.game.name}): {str(e)}")
            raise
        except Exception as e:
            self.price_data_failed_count += 1
            logger.error(f"❌ PROCESSING ERROR: Error processing item {item.name} ({self.game.name}): {str(e)}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=8, max=20),
        reraise=True
    )
    def _fetch_price_history(self, hash_name: str) -> dict:
        """Fetch full price history data for an item from Steam API"""
        url = "https://steamcommunity.com/market/pricehistory/"
        
        # Use Steam's specific encoding format instead of requests' automatic encoding
        import urllib.parse
        
        # Steam expects specific encoding for special characters
        # Convert spaces to %20, not + (which is the default)
        encoded_hash_name = urllib.parse.quote(hash_name, safe='')
        
        params = {
            'appid': self.game.value,
            'market_hash_name': encoded_hash_name,
            'currency': 1  # USD
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        }
        
        try:
            # Build URL manually to avoid requests' automatic encoding
            query_string = f"appid={self.game.value}&market_hash_name={encoded_hash_name}&currency=1"
            full_url = f"{url}?{query_string}"
            
            response = self.session.get(full_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Check if we have price history data
            if data.get('success') and 'prices' in data and data['prices']:
                logger.info(f"📊 FETCHED: {len(data['prices'])} price history entries for {hash_name} ({self.game.name})")
                return data
            else:
                logger.warning(f"📊 NO DATA: No price history data available for {hash_name} ({self.game.name})")
                return None
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning(f"🔄 HTTP RATE LIMITED: {hash_name} ({self.game.name}) - will retry with backoff")
                time.sleep(10)  # Additional sleep for rate limiting
                raise SteamAPIError(f"Rate limited: {str(e)}")
            else:
                logger.error(f"❌ HTTP ERROR: Error fetching price history for {hash_name} ({self.game.name}): {str(e)}")
                raise SteamAPIError(f"HTTP error: {str(e)}")
        except Exception as e:
            logger.error(f"❌ FETCH ERROR: Failed to fetch price history for {hash_name} ({self.game.name}): {str(e)}")
            raise SteamAPIError(f"Price history fetch failed: {str(e)}")
    
    def _rate_limit(self):
        """Implement rate limiting between requests"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_delay:
            sleep_time = self.min_delay - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _log_progress_summary(self):
        """Log a progress summary for the worker"""
        if self.processed_count > 0:
            success_rate = (self.price_data_success_count / self.processed_count) * 100
            logger.info(f"📊 {self.game.name} Progress Summary:")
            logger.info(f"   Processed: {self.processed_count} | Success: {self.price_data_success_count} | Failed: {self.price_data_failed_count}")
            logger.info(f"   Rate Limited: {self.rate_limited_count} | No Data: {self.no_price_data_count} | Success Rate: {success_rate:.1f}%")

class BatchProcessor:
    def __init__(self, session_cookies: Dict[str, str]):
        self.config = BatchConfig()
        # self.games = [Game.MAPLESTORY, Game.CS2]
        self.games = [Game.CS2]  # Only process CS2
        
        # Queue for each game to store processed items
        self.item_queues: Dict[Game, Queue] = {
            game: Queue() for game in self.games
        }
        
        # Priority queue for each game (for future price-based processing)
        self.priority_queues: Dict[Game, PriorityQueue] = {
            game: PriorityQueue() for game in self.games
        }
        
        # Track current page position for each game to avoid duplicates
        self.current_page: Dict[Game, int] = {
            game: 0 for game in self.games
        }
        
        # Track total items available for each game
        self.total_items: Dict[Game, int] = {
            game: 0 for game in self.games
        }
        
        # Thread safety
        self.queue_locks: Dict[Game, Lock] = {
            game: Lock() for game in self.games
        }
        
        # Worker management
        self.workers: Dict[Game, Worker] = {}
        self.stop_event = Event()
        self.database = DatabaseManager()
        
        self.base_url = 'https://steamcommunity.com/market'
        
        # Initialize session with cookies
        self.session = requests.Session()
        self.session.cookies.update(session_cookies)
        
        # Set user agent to mimic browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Configure logging
        logger.add("steam_market.log", rotation="1 day", retention="7 days", level="DEBUG")
        logger.add(lambda msg: print(msg, end=""), level="INFO")  # Console output
        
        # Load saved pagination state
        self._load_pagination_state()
        
        # Mark existing items as recently processed to avoid redundant fetching
        self.database.mark_all_existing_items_recently_processed()
        
        # Start workers
        self._start_workers()
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    def _make_api_request(self, game: Game, page: int) -> dict:
        """
        Make a request to the Steam Market API with rate limiting and retries.
        """
        # Use the search endpoint which returns JSON
        search_url = f"{self.base_url}/search/render"
        
        params = {
            'appid': game.value,
            'count': self.config.page_size,
            'start': page * self.config.page_size,
            'norender': 1,
            'search_descriptions': 0,
            'sort_column': 'default',
            'sort_dir': 'desc'
        }
        
        try:
            response = self.session.get(
                search_url,
                params=params,
                timeout=30
            )
            
            # Log response details for debugging
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            logger.debug(f"Response content (first 500 chars): {response.text[:500]}")
            
            response.raise_for_status()
            
            # Check if response is empty
            if not response.text.strip():
                logger.error(f"Empty response received for {game.name} page {page}")
                raise SteamAPIError("Empty response from Steam API")
            
            # Rate limiting delay
            time.sleep(self.config.min_delay_between_requests)
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed for {game.name} page {page}: {str(e)}")
            raise SteamAPIError(f"Failed to fetch market data: {str(e)}")
        except ValueError as e:
            logger.error(f"JSON parsing failed for {game.name} page {page}: {str(e)}")
            logger.error(f"Response content: {response.text}")
            raise SteamAPIError(f"Invalid JSON response: {str(e)}")
    
    def process_batch(self) -> None:
        """
        Process a single batch of items across all games.
        Each game gets its share of items (items_per_game),
        processed in pages of page_size items.
        """
        logger.info("Starting new batch processing cycle")
        
        for game in self.games:
            try:
                self._process_game_items(game)
            except Exception as e:
                logger.error(f"Error processing game {game.name}: {str(e)}")
                continue
            
        # Log queue statistics
        stats = self.get_queue_stats()
        logger.info("Queue statistics after batch:")
        for game_name, game_stats in stats.items():
            logger.info(f"  {game_name}: Main queue: {game_stats['main_queue_size']}, Priority queue: {game_stats['priority_queue_size']}")
        
        # Log worker statistics
        worker_stats = self.get_worker_stats()
        logger.info("Worker statistics:")
        for game_name, worker_stat in worker_stats.items():
            logger.info(f"  {game_name}: Processed: {worker_stat['processed_count']}, Errors: {worker_stat['error_count']}, Alive: {worker_stat['is_alive']}")
        
        # Log price history processing summary
        logger.info("Price history processing summary:")
        for game, worker in self.workers.items():
            logger.info(f"  {game.name}:")
            logger.info(f"    ✓ Successfully fetched: {worker.price_data_success_count}")
            logger.info(f"    ❌ Failed to fetch: {worker.price_data_failed_count}")
            logger.info(f"    🔄 Rate limited: {worker.rate_limited_count}")
            logger.info(f"    ⚠ No data available: {worker.no_price_data_count}")
            if worker.processed_count > 0:
                success_rate = (worker.price_data_success_count / worker.processed_count) * 100
                logger.info(f"    📊 Success rate: {success_rate:.1f}%")
        
        # Save pagination state after batch completion
        self._save_pagination_state()
        
        logger.info(f"Batch processing completed. Waiting {self.config.cooldown_minutes} minutes before next batch.")
        time.sleep(self.config.cooldown_minutes * 60)
    
    def _process_game_items(self, game: Game) -> None:
        """
        Process items for a specific game in pages, starting from the current tracked position.
        """
        logger.info(f"Processing items for game: {game.name} starting from page {self.current_page[game]}")
        
        pages_processed = 0
        items_processed = 0
        
        while pages_processed < self.config.pages_per_game:
            try:
                # Check if we've reached the end of available items
                if self.total_items[game] > 0 and self.current_page[game] * self.config.page_size >= self.total_items[game]:
                    logger.info(f"Reached end of available items for {game.name}. Resetting to page 0.")
                    self.current_page[game] = 0
                
                self._process_page(game, self.current_page[game])
                pages_processed += 1
                self.current_page[game] += 1
                
            except SteamAPIError as e:
                logger.error(f"Failed to process page {self.current_page[game]} for {game.name}: {str(e)}")
                # Move to next page even if current one failed
                self.current_page[game] += 1
                pages_processed += 1
                continue
    
    def _process_page(self, game: Game, page: int) -> None:
        """
        Process a single page of items for a game.
        """
        logger.info(f"Processing page {page + 1} for {game.name} (items {page * self.config.page_size}-{(page + 1) * self.config.page_size - 1})")
        
        try:
            market_data = self._make_api_request(game, page)
            
            # Update total items count if not set
            if self.total_items[game] == 0 and 'total_count' in market_data:
                self.total_items[game] = market_data['total_count']
                logger.info(f"Total items available for {game.name}: {self.total_items[game]}")
            
            # Process the market data - Steam API returns 'results' not 'listings'
            if 'results' in market_data and market_data['results']:
                for item in market_data['results']:
                    self._process_item(game, item)
                logger.info(f"Processed {len(market_data['results'])} items for {game.name} page {page + 1}")
            else:
                logger.warning(f"No results found in response for {game.name} page {page + 1}")
                
        except Exception as e:
            logger.error(f"Error processing page {page + 1} for {game.name}: {str(e)}")
            raise
    
    def _process_item(self, game: Game, item: dict) -> None:
        """
        Process a single market item and add it to the game's queue.
        """
        try:
            # Extract item details from Steam API response
            market_hash_name = item.get('hash_name')
            item_name = item.get('name')
            sell_price = item.get('sell_price', 0) / 100.0  # Convert cents to dollars
            sell_listings = item.get('sell_listings', 0)
            
            if not market_hash_name:
                logger.warning(f"Missing hash_name for item in {game.name}")
                return
            
            # Skip items with no active listings or zero price
            if sell_price <= 0 or sell_listings <= 0:
                logger.debug(f"Skipping item {item_name} with no active listings (price: ${sell_price:.2f}, listings: {sell_listings})")
                return
            
            # Create MarketItem and add to queue
            market_item = MarketItem(
                hash_name=market_hash_name,
                name=item_name,
                game=game,
                sell_price=sell_price,
                sell_listings=sell_listings,
                timestamp=time.time()
            )
            
            # Add to queue with thread safety
            with self.queue_locks[game]:
                self.item_queues[game].put(market_item)
                if self.priority_queues[game].qsize() < 1000:  # Limit priority queue size
                    self.priority_queues[game].put(market_item)
            
            logger.debug(f"Queued item: {market_item}")
            
        except Exception as e:
            logger.error(f"Error processing item in {game.name}: {str(e)}")
    
    def get_queue_stats(self) -> Dict[str, Dict[str, int]]:
        """Get statistics about all queues."""
        stats = {}
        for game in self.games:
            with self.queue_locks[game]:
                stats[game.name] = {
                    'main_queue_size': self.item_queues[game].qsize(),
                    'priority_queue_size': self.priority_queues[game].qsize()
                }
        return stats
    
    def get_items_from_queue(self, game: Game, count: int = 10) -> List[MarketItem]:
        """Get items from a game's queue."""
        items = []
        with self.queue_locks[game]:
            for _ in range(min(count, self.item_queues[game].qsize())):
                try:
                    items.append(self.item_queues[game].get_nowait())
                except:
                    break
        return items
    
    def clear_queue(self, game: Game) -> int:
        """Clear a game's queue and return the number of items cleared."""
        with self.queue_locks[game]:
            count = self.item_queues[game].qsize()
            while not self.item_queues[game].empty():
                try:
                    self.item_queues[game].get_nowait()
                except:
                    break
            return count
    
    def demonstrate_queue_usage(self) -> None:
        """Demonstrate how to use the queues."""
        logger.info("Demonstrating queue usage:")
        
        # Show current queue stats
        stats = self.get_queue_stats()
        for game_name, game_stats in stats.items():
            logger.info(f"  {game_name}: {game_stats['main_queue_size']} items in main queue")
        
        # Get some items from each queue
        for game in self.games:
            items = self.get_items_from_queue(game, count=5)
            if items:
                logger.info(f"Sample items from {game.name} queue:")
                for item in items:
                    logger.info(f"  - {item}")
            else:
                logger.info(f"No items in {game.name} queue yet")

    def _save_pagination_state(self) -> None:
        """Save current pagination state to file for persistence."""
        state = {
            'current_page': {game.name: page for game, page in self.current_page.items()},
            'total_items': {game.name: total for game, total in self.total_items.items()},
            'processed_items_count': {game.name: self.item_queues[game].qsize() for game in self.games}
        }
        
        try:
            with open('pagination_state.json', 'w') as f:
                json.dump(state, f, indent=2)
            logger.debug("Pagination state saved")
        except Exception as e:
            logger.error(f"Failed to save pagination state: {str(e)}")
    
    def _load_pagination_state(self) -> None:
        """Load pagination state from file if it exists."""
        try:
            if os.path.exists('pagination_state.json'):
                with open('pagination_state.json', 'r') as f:
                    state = json.load(f)
                
                # Restore current page positions
                for game_name, page in state.get('current_page', {}).items():
                    try:
                        game = Game[game_name]
                        self.current_page[game] = page
                    except KeyError:
                        logger.warning(f"Unknown game in saved state: {game_name}")
                
                # Restore total items count
                for game_name, total in state.get('total_items', {}).items():
                    try:
                        game = Game[game_name]
                        self.total_items[game] = total
                    except KeyError:
                        logger.warning(f"Unknown game in saved state: {game_name}")
                
                logger.info("Pagination state loaded from file")
            else:
                logger.info("No saved pagination state found, starting fresh")
        except Exception as e:
            logger.error(f"Failed to load pagination state: {str(e)}")

    def _start_workers(self):
        """Start worker threads for each game"""
        for game in self.games:
            worker = Worker(game, self.item_queues[game], self.session, self.database, self.stop_event)
            self.workers[game] = worker
            worker.start()
    
    def stop_workers(self):
        """Stop all worker threads gracefully"""
        logger.info("Stopping all workers...")
        self.stop_event.set()
        
        for game, worker in self.workers.items():
            worker.join(timeout=10)  # Wait up to 10 seconds for each worker
            if worker.is_alive():
                logger.warning(f"Worker for {game.name} did not stop gracefully")
        
        logger.info("All workers stopped")
    
    def get_worker_stats(self) -> Dict[str, Dict[str, int]]:
        """Get statistics about all workers"""
        stats = {}
        for game, worker in self.workers.items():
            stats[game.name] = {
                'processed_count': worker.processed_count,
                'error_count': worker.error_count,
                'is_alive': worker.is_alive(),
                'price_data_success': worker.price_data_success_count,
                'price_data_failed': worker.price_data_failed_count,
                'rate_limited': worker.rate_limited_count,
                'no_price_data': worker.no_price_data_count
            }
        return stats

def main():
    # Example session cookies - you'll need to replace these with actual cookies
    session_cookies = {
        'sessionid': 'acc776ba86880c3cca3d9697',
        'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwRV8yNjk5RTA5QV83OEJDOCIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NTIzMzYyODksICJuYmYiOiAxNzQzNjA5NTA0LCAiaWF0IjogMTc1MjI0OTUwNCwgImp0aSI6ICIwMDBCXzI2OTlFMDlCXzczNkM0IiwgIm9hdCI6IDE3NTIyNDk1MDMsICJydF9leHAiOiAxNzU0ODQ1Njc1LCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiMTA4LjM1LjIwMS4yMjgiLCAiaXBfY29uZmlybWVyIjogIjEwOC4zNS4yMDEuMjI4IiB9.bIZRGs_FhA0vmpuX3f8nmZIZ_rC79xlQ0uzkSUxSYrKPQeFNcyYA1Zwpbq0o3UktzdZbDBvbnUK4tTGDpXSUBg',
        # Add other necessary cookies as needed
    }
    
    processor = None
    try:
        processor = BatchProcessor(session_cookies)
        
        # Test mode: run one batch and demonstrate queues
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == '--test':
            logger.info("Running in test mode - processing one batch")
            processor.process_batch()
            processor.demonstrate_queue_usage()
            
            # Show final worker stats
            worker_stats = processor.get_worker_stats()
            logger.info("Final worker statistics:")
            for game_name, worker_stat in worker_stats.items():
                logger.info(f"  {game_name}: Processed: {worker_stat['processed_count']}, Errors: {worker_stat['error_count']}")
                logger.info(f"    Price Data - Success: {worker_stat['price_data_success']}, Failed: {worker_stat['price_data_failed']}")
                logger.info(f"    Rate Limited: {worker_stat['rate_limited']}, No Data: {worker_stat['no_price_data']}")
                if worker_stat['processed_count'] > 0:
                    success_rate = (worker_stat['price_data_success'] / worker_stat['processed_count']) * 100
                    logger.info(f"    Success Rate: {success_rate:.1f}%")
            
            return
        
        # Normal mode: continuous processing
        while True:
            processor.process_batch()
    except KeyboardInterrupt:
        logger.info("Batch processing stopped by user")
        if processor:
            # Show final queue stats
            processor.demonstrate_queue_usage()
            
            # Show final worker stats
            worker_stats = processor.get_worker_stats()
            logger.info("Final worker statistics:")
            for game_name, worker_stat in worker_stats.items():
                logger.info(f"  {game_name}: Processed: {worker_stat['processed_count']}, Errors: {worker_stat['error_count']}")
                logger.info(f"    Price Data - Success: {worker_stat['price_data_success']}, Failed: {worker_stat['price_data_failed']}")
                logger.info(f"    Rate Limited: {worker_stat['rate_limited']}, No Data: {worker_stat['no_price_data']}")
                if worker_stat['processed_count'] > 0:
                    success_rate = (worker_stat['price_data_success'] / worker_stat['processed_count']) * 100
                    logger.info(f"    Success Rate: {success_rate:.1f}%")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise
    finally:
        if processor:
            processor.stop_workers()

if __name__ == "__main__":
    main() 