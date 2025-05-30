import requests
import time
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import logging
import json
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('market_data.log'),
        logging.StreamHandler()
    ]
)

class MarketDataCollector:
    def __init__(self, db_path='market_data.db'):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9'
        })
        self.rate_limit = {
            'requests': 0,
            'last_reset': time.time(),
            'max_requests': 20,  # Steam's rate limit
            'reset_interval': 60  # Reset every 60 seconds
        }
        self.initialize_database()

    def initialize_database(self):
        """Initialize SQLite database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create items table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    market_hash_name TEXT UNIQUE,
                    image_url TEXT,
                    last_updated TIMESTAMP
                )
            ''')
            
            # Create price_history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY,
                    item_id INTEGER,
                    timestamp TIMESTAMP,
                    price REAL,
                    volume INTEGER,
                    FOREIGN KEY (item_id) REFERENCES items(id)
                )
            ''')
            
            conn.commit()

    def check_rate_limit(self):
        """Check and update rate limiting."""
        current_time = time.time()
        if current_time - self.rate_limit['last_reset'] >= self.rate_limit['reset_interval']:
            self.rate_limit['requests'] = 0
            self.rate_limit['last_reset'] = current_time
        
        if self.rate_limit['requests'] >= self.rate_limit['max_requests']:
            sleep_time = self.rate_limit['reset_interval'] - (current_time - self.rate_limit['last_reset'])
            if sleep_time > 0:
                logging.info(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
                self.rate_limit['requests'] = 0
                self.rate_limit['last_reset'] = time.time()
        
        self.rate_limit['requests'] += 1

    def fetch_all_items(self):
        """Fetch all MapleStory items from Steam Market."""
        items = []
        start = 0
        total_items = 0
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while True:
            try:
                self.check_rate_limit()
                url = "https://steamcommunity.com/market/search/render/"
                params = {
                    "appid": "216150",
                    "norender": 1,
                    "count": 100,
                    "start": start
                }
                
                response = self.session.get(url, params=params)
                
                # Check if response is valid
                if response.status_code != 200:
                    logging.error(f"API returned status code {response.status_code}")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logging.error("Too many consecutive errors, stopping fetch")
                        break
                    time.sleep(5)
                    continue
                
                try:
                    data = response.json()
                except json.JSONDecodeError:
                    logging.error("Failed to decode JSON response")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logging.error("Too many consecutive errors, stopping fetch")
                        break
                    time.sleep(5)
                    continue
                
                if not data or not isinstance(data, dict):
                    logging.error("Invalid response format")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logging.error("Too many consecutive errors, stopping fetch")
                        break
                    time.sleep(5)
                    continue
                
                if not data.get("results"):
                    logging.info("No more items to fetch")
                    break
                
                batch_items = data["results"]
                items.extend(batch_items)
                total_items += len(batch_items)
                logging.info(f"Fetched {len(batch_items)} items. Total: {total_items}")
                
                # Reset consecutive errors counter on success
                consecutive_errors = 0
                
                start += 100
                time.sleep(10)  # Additional delay between batches
                
            except Exception as e:
                logging.error(f"Error fetching items: {str(e)}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logging.error("Too many consecutive errors, stopping fetch")
                    break
                time.sleep(5)  # Wait longer on error
                continue
        
        return items

    def fetch_price_history(self, market_hash_name):
        """Fetch price history for a specific item."""
        try:
            self.check_rate_limit()
            url = "https://steamcommunity.com/market/pricehistory/"
            params = {
                "appid": "216150",
                "market_hash_name": market_hash_name,
                "currency": 1
            }
            
            response = self.session.get(url, params=params)
            return response.json()
            
        except Exception as e:
            logging.error(f"Error fetching price history for {market_hash_name}: {str(e)}")
            return None

    def store_items(self, items):
        """Store items in the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for item in items:
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO items (name, market_hash_name, image_url, last_updated)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        item.get('name'),
                        item.get('hash_name'),
                        item.get('asset_description', {}).get('icon_url'),
                        datetime.now()
                    ))
                except Exception as e:
                    logging.error(f"Error storing item {item.get('name')}: {str(e)}")
            conn.commit()

    def store_price_history(self, item_id, price_data):
        """Store price history in the database."""
        if not price_data or 'prices' not in price_data:
            return
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for price_point in price_data['prices']:
                try:
                    timestamp = datetime.strptime(price_point[0], '%b %d %Y %H: +0')
                    cursor.execute('''
                        INSERT OR REPLACE INTO price_history (item_id, timestamp, price, volume)
                        VALUES (?, ?, ?, ?)
                    ''', (item_id, timestamp, price_point[1], price_point[2]))
                except Exception as e:
                    logging.error(f"Error storing price history for item {item_id}: {str(e)}")
            conn.commit()

    def update_all_data(self):
        """Update all items and their price histories."""
        # Fetch and store items
        items = self.fetch_all_items()
        self.store_items(items)
        
        # Fetch and store price histories
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, market_hash_name FROM items")
            items = cursor.fetchall()
            
            for item_id, market_hash_name in items:
                price_data = self.fetch_price_history(market_hash_name)
                if price_data:
                    self.store_price_history(item_id, price_data)
                time.sleep(1)  # Delay between items

class PricePredictor:
    def __init__(self, db_path='market_data.db'):
        self.db_path = db_path
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.scaler = StandardScaler()

    def prepare_features(self, item_id, lookback_days=7):
        """Prepare features for a specific item."""
        with sqlite3.connect(self.db_path) as conn:
            query = f"""
                SELECT timestamp, price, volume
                FROM price_history
                WHERE item_id = ?
                ORDER BY timestamp
            """
            df = pd.read_sql_query(query, conn, params=(item_id,))
            
            if df.empty:
                return None, None
            
            # Create time-based features
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['day_of_week'] = df['timestamp'].dt.dayofweek
            df['month'] = df['timestamp'].dt.month
            
            # Create lagged features
            for i in range(1, lookback_days + 1):
                df[f'price_lag_{i}'] = df['price'].shift(i)
                df[f'volume_lag_{i}'] = df['volume'].shift(i)
            
            # Create target (next day's price)
            df['target'] = df['price'].shift(-1)
            
            # Drop rows with NaN values
            df = df.dropna()
            
            if df.empty:
                return None, None
            
            # Prepare features and target
            feature_columns = [col for col in df.columns if col not in ['timestamp', 'target']]
            X = df[feature_columns]
            y = df['target']
            
            return X, y

    def train_model(self, item_id):
        """Train model for a specific item."""
        X, y = self.prepare_features(item_id)
        if X is None or y is None:
            logging.warning(f"Not enough data to train model for item {item_id}")
            return False
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Train model
        self.model.fit(X_train_scaled, y_train)
        
        # Evaluate
        score = self.model.score(X_test_scaled, y_test)
        logging.info(f"Model R² score for item {item_id}: {score:.4f}")
        
        return True

    def predict_price(self, item_id, days_ahead=1):
        """Predict future price for a specific item."""
        X, _ = self.prepare_features(item_id)
        if X is None:
            return None
        
        # Get the most recent data point
        latest_data = X.iloc[-1:].copy()
        
        # Scale features
        latest_data_scaled = self.scaler.transform(latest_data)
        
        # Make prediction
        prediction = self.model.predict(latest_data_scaled)[0]
        
        return prediction

def main():
    # Initialize collector
    collector = MarketDataCollector()
    
    # Update data
    collector.update_all_data()
    
    # Initialize predictor
    predictor = PricePredictor()
    
    # Train models for all items
    with sqlite3.connect(collector.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM items")
        item_ids = cursor.fetchall()
        
        for (item_id,) in item_ids:
            predictor.train_model(item_id)

if __name__ == "__main__":
    main() 