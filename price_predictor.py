import sqlite3
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
import joblib
from datetime import datetime, timedelta
import logging

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
    def __init__(self, db_path='market_data.db'):
        self.db_path = db_path
        self.models = {}
        self.scalers = {}
        
    def prepare_data(self, game_id, lookback_days=30, prediction_days=7):
        """
        Prepare data for training by creating features from historical prices
        """
        with sqlite3.connect(self.db_path) as conn:
            # Get all items for the specified game
            items_query = '''
                SELECT id, market_hash_name 
                FROM items 
                WHERE game_id = ?
            '''
            items_df = pd.read_sql_query(items_query, conn, params=(game_id,))
            
            all_features = []
            all_targets = []
            item_names = []
            
            for _, item in items_df.iterrows():
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
                price_df['timestamp'] = pd.to_datetime(price_df['timestamp'])
                
                # Create features using rolling windows
                price_df['price_ma7'] = price_df['price'].rolling(window=7).mean()
                price_df['price_ma30'] = price_df['price'].rolling(window=30).mean()
                price_df['price_std7'] = price_df['price'].rolling(window=7).std()
                price_df['volume_ma7'] = price_df['volume'].rolling(window=7).mean()
                
                # Create target (future price)
                price_df['future_price'] = price_df['price'].shift(-prediction_days)
                
                # Drop rows with NaN values
                price_df = price_df.dropna()
                
                if len(price_df) > 0:
                    features = price_df[['price', 'price_ma7', 'price_ma30', 'price_std7', 'volume_ma7']].values
                    targets = price_df['future_price'].values
                    
                    all_features.extend(features)
                    all_targets.extend(targets)
                    item_names.extend([item['market_hash_name']] * len(features))
            
            if not all_features:
                return None, None, None
            
            return np.array(all_features), np.array(all_targets), item_names
    
    def train_model(self, game_id):
        """
        Train a Random Forest model for the specified game
        """
        logging.info(f"Training model for {game_id}")
        
        # Prepare data
        X, y, item_names = self.prepare_data(game_id)
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
        r2 = r2_score(y_test, y_pred)
        
        logging.info(f"Model performance for {game_id}:")
        logging.info(f"Mean Squared Error: {mse:.4f}")
        logging.info(f"R2 Score: {r2:.4f}")
        
        # Save model and scaler
        self.models[game_id] = model
        self.scalers[game_id] = scaler
        
        return True
    
    def predict_price(self, game_id, item_name, current_price, current_volume):
        """
        Predict future price for a specific item
        """
        if game_id not in self.models:
            if not self.train_model(game_id):
                return None
        
        # Prepare features
        features = np.array([[
            current_price,
            current_price,  # price_ma7 (using current price as approximation)
            current_price,  # price_ma30 (using current price as approximation)
            0,  # price_std7 (using 0 as approximation)
            current_volume  # volume_ma7 (using current volume as approximation)
        ]])
        
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
        
        for game_id in ['csgo', 'maplestory']:
            model_path = f'{path}/{game_id}_model.joblib'
            scaler_path = f'{path}/{game_id}_scaler.joblib'
            
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                self.models[game_id] = joblib.load(model_path)
                self.scalers[game_id] = joblib.load(scaler_path)
        
        return len(self.models) > 0

def main():
    # Initialize predictor
    predictor = PricePredictor()
    
    # Train models for both games
    for game_id in ['csgo', 'maplestory']:
        predictor.train_model(game_id)
    
    # Save models
    predictor.save_models()
    
    # Example prediction
    if 'csgo' in predictor.models:
        current_price = 10.0
        current_volume = 1000
        predicted_price = predictor.predict_price('csgo', 'Operation Breakout Weapon Case', current_price, current_volume)
        logging.info(f"Predicted price for Operation Breakout Weapon Case: ${predicted_price:.2f}")

if __name__ == '__main__':
    main() 