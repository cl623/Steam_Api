import sqlite3
import pandas as pd
import numpy as np
import os
import time
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
import joblib
from datetime import datetime, timedelta
import logging
from .feature_extractor import ItemFeatureExtractor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('price_prediction.log'),
        logging.StreamHandler()
    ]
)

class PricePredictor:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'market_data.db')
        self.db_path = db_path
        self.models = {}
        self.scalers = {}
        self.feature_extractor = ItemFeatureExtractor()
    
    def _parse_steam_timestamp(self, ts_str):
        """Parse Steam timestamp format to datetime"""
        try:
            import re
            # Remove timezone offset
            clean_ts = re.sub(r'\s+\+\d+$', '', str(ts_str)).strip()
            # Parse format: "Apr 01 2014 01:"
            parts = re.match(r'(\w+)\s+(\d+)\s+(\d+)\s+(\d+):', clean_ts)
            if parts:
                month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                month = month_names.index(parts.group(1)) + 1
                day = int(parts.group(2))
                year = int(parts.group(3))
                hour = int(parts.group(4))
                return pd.Timestamp(year, month, day, hour)
        except (ValueError, AttributeError, IndexError):
            pass
        return pd.NaT
    
    def get_moving_averages_from_db(self, item_name, game_id, days=30):
        """
        Calculate moving averages from database for a specific item.
        
        Args:
            item_name: Market hash name of the item
            game_id: Game ID
            days: Number of days of history to use (default: 30)
            
        Returns:
            dict with keys: price_ma7, price_ma30, price_std7, volume_ma7, current_price, current_volume
            Returns None if insufficient data
        """
        with sqlite3.connect(self.db_path) as conn:
            # Get item ID
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM items 
                WHERE market_hash_name = ? AND game_id = ?
            ''', (item_name, game_id))
            result = cursor.fetchone()
            
            if not result:
                logging.warning(f"Item not found in database: {item_name}")
                return None
            
            item_id = result[0]
            
            # Get price history - get most recent entries, then sort ascending
            price_query = '''
                SELECT timestamp, price, volume
                FROM price_history
                WHERE item_id = ?
                ORDER BY timestamp ASC
            '''
            price_df = pd.read_sql_query(price_query, conn, params=(item_id,))
            
            if len(price_df) < 7:
                logging.warning(f"Insufficient data for {item_name}: {len(price_df)} entries (need at least 7)")
                return None
            
            # Parse timestamps
            price_df['timestamp'] = price_df['timestamp'].apply(self._parse_steam_timestamp)
            price_df = price_df.dropna(subset=['timestamp'])
            price_df = price_df.sort_values('timestamp')
            
            if len(price_df) < 7:
                return None
            
            # Get only the most recent entries (last N days worth)
            price_df = price_df.tail(days)
            
            # Get current values (most recent)
            current_price = float(price_df['price'].iloc[-1])
            current_volume = int(price_df['volume'].iloc[-1])
            
            # Calculate moving averages from the most recent data
            window_7 = min(7, len(price_df))
            window_30 = min(30, len(price_df))
            
            # Use tail() to get most recent values for MAs
            price_ma7 = float(price_df['price'].tail(window_7).mean())
            price_ma30 = float(price_df['price'].tail(window_30).mean()) if window_30 >= 7 else price_ma7
            price_std7 = float(price_df['price'].tail(window_7).std()) if window_7 > 1 else 0.0
            volume_ma7 = float(price_df['volume'].tail(window_7).mean())
            
            return {
                'current_price': current_price,
                'current_volume': current_volume,
                'price_ma7': price_ma7,
                'price_ma30': price_ma30,
                'price_std7': price_std7,
                'volume_ma7': volume_ma7
            }
        
    def prepare_data(self, game_id, lookback_days=7, prediction_days=7, max_items=None, pause_check=None):
        """
        Prepare data for training by creating features from historical prices
        and item name parsing.
        
        Args:
            game_id: Game ID to process
            lookback_days: Number of days to look back for features
            prediction_days: Number of days ahead to predict
            max_items: Maximum number of items to process (None for all items)
            pause_check: Optional callable that returns True if should pause (called after each item)
        
        Returns:
            X: Feature matrix (numpy array)
            y: Target prices (numpy array)
            item_names: List of item names for each sample
        """
        with sqlite3.connect(self.db_path) as conn:
            # Get items with sufficient price history data
            # First, get items that have at least (lookback_days + prediction_days) entries
            min_entries = lookback_days + prediction_days
            items_query = '''
                SELECT i.id, i.market_hash_name, COUNT(ph.id) as entry_count
                FROM items i
                JOIN price_history ph ON i.id = ph.item_id
                WHERE i.game_id = ?
                GROUP BY i.id, i.market_hash_name
                HAVING COUNT(ph.id) >= ?
                ORDER BY entry_count DESC
            '''
            items_df = pd.read_sql_query(items_query, conn, params=(game_id, min_entries))
            
            # Limit items if max_items is specified
            if max_items is not None and max_items > 0:
                items_df = items_df.head(max_items)
                logging.info(f"Sample mode: Processing {len(items_df)} items (limited from {len(items_df)} available)")
            else:
                logging.info(f"Full mode: Processing {len(items_df)} items for game {game_id}")
            
            if len(items_df) == 0:
                logging.warning(f"No items found with at least {min_entries} price history entries")
                return None, None, None
            
            all_features = []
            all_targets = []
            item_names = []
            
            items_processed = 0
            items_with_features = 0
            
            for idx, item in items_df.iterrows():
                # Check for pause request
                if pause_check and pause_check():
                    logging.info("Training paused by pause_check callback")
                    # Wait until resume
                    while pause_check():
                        time.sleep(1)
                    logging.info("Training resumed")
                
                if (idx + 1) % 10 == 0 or (idx + 1) == len(items_df):
                    logging.info(f"Processing item {idx + 1}/{len(items_df)} (found features for {items_with_features} items)")
                
                # Get price history for the item
                price_query = '''
                    SELECT timestamp, price, volume
                    FROM price_history
                    WHERE item_id = ?
                    ORDER BY timestamp ASC
                '''
                price_df = pd.read_sql_query(price_query, conn, params=(item['id'],))
                
                if len(price_df) < lookback_days + prediction_days:
                    continue
                
                # Convert timestamp to datetime
                price_df['timestamp'] = price_df['timestamp'].apply(self._parse_steam_timestamp)
                price_df = price_df.dropna(subset=['timestamp'])
                
                if len(price_df) < lookback_days + prediction_days:
                    continue
                
                # Create features using rolling windows
                # Use smaller windows if we don't have enough data
                available_days = len(price_df)
                window_7 = min(7, available_days - 1) if available_days > 1 else 1
                window_30 = min(30, available_days - 1) if available_days > 1 else 1
                
                price_df['price_ma7'] = price_df['price'].rolling(window=window_7).mean()
                price_df['price_ma30'] = price_df['price'].rolling(window=min(window_30, window_7)).mean()
                price_df['price_std7'] = price_df['price'].rolling(window=window_7).std()
                price_df['volume_ma7'] = price_df['volume'].rolling(window=window_7).mean()
                
                # Fill NaN values in rolling averages with current value or 0
                price_df['price_ma7'] = price_df['price_ma7'].fillna(price_df['price'])
                price_df['price_ma30'] = price_df['price_ma30'].fillna(price_df['price'])
                price_df['price_std7'] = price_df['price_std7'].fillna(0.0)
                price_df['volume_ma7'] = price_df['volume_ma7'].fillna(price_df['volume'])
                
                # Create target (future price)
                price_df['future_price'] = price_df['price'].shift(-prediction_days)
                
                # Only drop rows where future_price is NaN (can't predict without target)
                price_df = price_df.dropna(subset=['future_price'])
                
                if len(price_df) > 0:
                    items_with_features += 1
                    # Extract item name features
                    item_features = self.feature_extractor.get_feature_vector(item['market_hash_name'])
                    
                    # Combine price/volume features with item name features
                    for _, row in price_df.iterrows():
                        # Price/volume features
                        price_features = [
                            row['price'],
                            row['price_ma7'],
                            row['price_ma30'],
                            row['price_std7'] if not pd.isna(row['price_std7']) else 0.0,
                            row['volume_ma7'],
                        ]
                        
                        # Item name features (convert dict to list in consistent order)
                        item_feature_list = [
                            item_features['type_weapon_skin'],
                            item_features['type_sticker'],
                            item_features['type_case'],
                            item_features['type_agent'],
                            item_features['type_gloves'],
                            item_features['type_knife'],
                            item_features['type_other'],
                            item_features['is_weapon_skin'],
                            item_features['condition_quality'],
                            item_features['is_stattrak'],
                            item_features['is_souvenir'],
                            item_features['has_sticker'],
                            item_features['is_case'],
                            item_features['is_sticker'],
                            item_features['is_agent'],
                            item_features['is_gloves'],
                            item_features['is_knife'],
                        ]
                        
                        # Combine all features
                        combined_features = price_features + item_feature_list
                        all_features.append(combined_features)
                        all_targets.append(row['future_price'])
                        item_names.append(item['market_hash_name'])
            
            logging.info(f"Processed {len(items_df)} items, extracted features from {items_with_features} items")
            
            if not all_features:
                logging.warning(f"No features extracted for game {game_id}")
                return None, None, None
            
            logging.info(f"Extracted {len(all_features)} samples with {len(all_features[0])} features each")
            return np.array(all_features), np.array(all_targets), item_names
    
    def train_model(self, game_id, max_items=None, pause_check=None):
        """
        Train a Random Forest model for the specified game
        
        Args:
            game_id: Game ID to train for
            max_items: Maximum number of items to use (None for all items)
            pause_check: Optional callable that returns True if should pause
        """
        mode_str = f"sample mode ({max_items} items)" if max_items else "full mode"
        logging.info(f"Training model for {game_id} in {mode_str}")
        
        # Prepare data
        X, y, item_names = self.prepare_data(game_id, max_items=max_items, pause_check=pause_check)
        if X is None:
            logging.error(f"No data available for {game_id}")
            return False
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train model
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(X_train_scaled, y_train)
        
        # Evaluate model
        y_pred = model.predict(X_test_scaled)
        mse = mean_squared_error(y_test, y_pred)
        rmse = np.sqrt(mse)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        logging.info(f"Model performance for {game_id}:")
        logging.info(f"  Mean Squared Error: {mse:.4f}")
        logging.info(f"  Root Mean Squared Error: ${rmse:.4f}")
        logging.info(f"  Mean Absolute Error: ${mae:.4f}")
        logging.info(f"  R2 Score: {r2:.4f}")
        
        # Feature importance
        feature_importance = model.feature_importances_
        logging.info(f"  Top 5 most important features:")
        feature_names = [
            'price', 'price_ma7', 'price_ma30', 'price_std7', 'volume_ma7',
            'type_weapon_skin', 'type_sticker', 'type_case', 'type_agent', 'type_gloves',
            'type_knife', 'type_other', 'is_weapon_skin', 'condition_quality',
            'is_stattrak', 'is_souvenir', 'has_sticker', 'is_case', 'is_sticker',
            'is_agent', 'is_gloves', 'is_knife'
        ]
        top_indices = np.argsort(feature_importance)[-5:][::-1]
        for idx in top_indices:
            logging.info(f"    {feature_names[idx]}: {feature_importance[idx]:.4f}")
        
        # Save model and scaler
        self.models[game_id] = model
        self.scalers[game_id] = scaler
        
        return True
    
    def predict_price(self, game_id, item_name, current_price=None, current_volume=None, 
                     price_ma7=None, price_ma30=None, price_std7=None, volume_ma7=None,
                     auto_calculate_ma=True):
        """
        Predict future price for a specific item.
        
        IMPROVED: Now automatically calculates moving averages from database if not provided.
        
        Args:
            game_id: Game ID
            item_name: Market hash name of the item
            current_price: Current price (optional if auto_calculate_ma=True)
            current_volume: Current volume (optional if auto_calculate_ma=True)
            price_ma7: Optional 7-day moving average (auto-calculated if None and auto_calculate_ma=True)
            price_ma30: Optional 30-day moving average (auto-calculated if None and auto_calculate_ma=True)
            price_std7: Optional 7-day standard deviation (auto-calculated if None and auto_calculate_ma=True)
            volume_ma7: Optional 7-day volume moving average (auto-calculated if None and auto_calculate_ma=True)
            auto_calculate_ma: If True, automatically fetch and calculate MAs from database (default: True)
        
        Returns:
            Predicted price, or None if prediction fails
        """
        if game_id not in self.models:
            if not self.train_model(game_id):
                return None
        
        # Auto-calculate moving averages from database if enabled and not provided
        if auto_calculate_ma and (price_ma7 is None or price_ma30 is None):
            ma_data = self.get_moving_averages_from_db(item_name, game_id, days=30)
            
            if ma_data:
                # Use calculated values, with provided values taking precedence
                current_price = current_price if current_price is not None else ma_data['current_price']
                current_volume = current_volume if current_volume is not None else ma_data['current_volume']
                price_ma7 = price_ma7 if price_ma7 is not None else ma_data['price_ma7']
                price_ma30 = price_ma30 if price_ma30 is not None else ma_data['price_ma30']
                price_std7 = price_std7 if price_std7 is not None else ma_data['price_std7']
                volume_ma7 = volume_ma7 if volume_ma7 is not None else ma_data['volume_ma7']
                
                logging.debug(f"Auto-calculated MAs for {item_name}: ma7=${price_ma7:.2f}, ma30=${price_ma30:.2f}")
            else:
                # Fall back to defaults if database lookup fails
                logging.warning(f"Could not calculate MAs from database for {item_name}, using defaults")
                if current_price is None:
                    logging.error("current_price required when auto_calculate_ma fails")
                    return None
                price_ma7 = price_ma7 if price_ma7 is not None else current_price
                price_ma30 = price_ma30 if price_ma30 is not None else current_price
                price_std7 = price_std7 if price_std7 is not None else 0.0
                volume_ma7 = volume_ma7 if volume_ma7 is not None else current_volume
        else:
            # Use provided values or defaults
            if current_price is None:
                logging.error("current_price is required")
                return None
            price_ma7 = price_ma7 if price_ma7 is not None else current_price
            price_ma30 = price_ma30 if price_ma30 is not None else current_price
            price_std7 = price_std7 if price_std7 is not None else 0.0
            volume_ma7 = volume_ma7 if volume_ma7 is not None else (current_volume if current_volume is not None else 0)
        
        # Extract item name features
        item_features = self.feature_extractor.get_feature_vector(item_name)
        
        # Price/volume features
        price_features = [
            current_price,
            price_ma7,
            price_ma30,
            price_std7,
            volume_ma7,
        ]
        
        # Item name features (same order as in prepare_data)
        item_feature_list = [
            item_features['type_weapon_skin'],
            item_features['type_sticker'],
            item_features['type_case'],
            item_features['type_agent'],
            item_features['type_gloves'],
            item_features['type_knife'],
            item_features['type_other'],
            item_features['is_weapon_skin'],
            item_features['condition_quality'],
            item_features['is_stattrak'],
            item_features['is_souvenir'],
            item_features['has_sticker'],
            item_features['is_case'],
            item_features['is_sticker'],
            item_features['is_agent'],
            item_features['is_gloves'],
            item_features['is_knife'],
        ]
        
        # Combine all features
        features = np.array([price_features + item_feature_list])
        
        # Scale features
        features_scaled = self.scalers[game_id].transform(features)
        
        # Make prediction
        prediction = self.models[game_id].predict(features_scaled)[0]
        
        return prediction
    
    def save_models(self, path='models'):
        """
        Save trained models and scalers
        """
        import os
        os.makedirs(path, exist_ok=True)
        
        for game_id in self.models:
            joblib.dump(self.models[game_id], f'{path}/{game_id}_model.joblib')
            joblib.dump(self.scalers[game_id], f'{path}/{game_id}_scaler.joblib')
    
    def load_models(self, path='models'):
        """
        Load trained models and scalers
        """
        import os
        if not os.path.exists(path):
            return False
        
        # Use numeric game IDs to match the rest of the codebase
        for game_id in [
            '730',  # Counter-Strike 2
            # '216150',  # MapleStory - commented out, focusing on CS2
        ]:
            model_path = f'{path}/{game_id}_model.joblib'
            scaler_path = f'{path}/{game_id}_scaler.joblib'
            
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                self.models[game_id] = joblib.load(model_path)
                self.scalers[game_id] = joblib.load(scaler_path)
        
        return len(self.models) > 0

def main():
    # Initialize predictor
    predictor = PricePredictor()
    
    # Train models for both games (using numeric IDs to match database)
    for game_id in [
        '730',  # Counter-Strike 2
        # '216150',  # MapleStory - commented out, focusing on CS2
    ]:
        predictor.train_model(game_id)
    
    # Save models
    predictor.save_models()
    
    # Example prediction with auto-calculated MAs
    if '730' in predictor.models:
        # Simple usage - MAs auto-calculated from database
        predicted_price = predictor.predict_price('730', 'Operation Breakout Weapon Case')
        logging.info(f"Predicted price for Operation Breakout Weapon Case: ${predicted_price:.2f}")

if __name__ == '__main__':
    main()
