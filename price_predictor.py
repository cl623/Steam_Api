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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('price_predictor.log'),
        logging.StreamHandler()
    ]
)

class PricePredictor:
    def __init__(self, db_path='steam_market.db'):
        self.db_path = db_path
        self.model = None
        self.scaler = StandardScaler()
        
    def load_data(self):
        """Load and prepare data from SQLite database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Query to get price history with item details
                query = """
                SELECT 
                    ph.timestamp,
                    ph.price,
                    ph.volume,
                    i.market_hash_name,
                    i.game_id
                FROM price_history ph
                JOIN items i ON ph.item_id = i.id
                ORDER BY ph.timestamp
                """
                
                df = pd.read_sql_query(query, conn)
                
                # Convert timestamp to datetime
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                logging.info(f"Loaded {len(df)} price history records")
                return df
                
        except Exception as e:
            logging.error(f"Error loading data: {str(e)}")
            return None

    def create_features(self, df):
        """Create features for the model"""
        try:
            # Group by item and create time-based features
            df_features = []
            
            for (market_hash_name, game_id), group in df.groupby(['market_hash_name', 'game_id']):
                # Sort by timestamp
                group = group.sort_values('timestamp')
                
                # Create time-based features
                group['hour'] = group['timestamp'].dt.hour
                group['day_of_week'] = group['timestamp'].dt.dayofweek
                group['month'] = group['timestamp'].dt.month
                
                # Create price-based features
                group['price_change'] = group['price'].pct_change()
                group['price_volatility'] = group['price'].rolling(window=24).std()
                group['price_moving_avg'] = group['price'].rolling(window=24).mean()
                
                # Create volume-based features
                group['volume_change'] = group['volume'].pct_change()
                group['volume_moving_avg'] = group['volume'].rolling(window=24).mean()
                
                # Add game-specific features
                group['is_cs2'] = (game_id == '730').astype(int)
                group['is_maplestory'] = (game_id == '216150').astype(int)
                
                df_features.append(group)
            
            # Combine all features
            final_df = pd.concat(df_features)
            
            # Drop rows with NaN values
            final_df = final_df.dropna()
            
            # Select features for model
            feature_columns = [
                'hour', 'day_of_week', 'month',
                'price_change', 'price_volatility', 'price_moving_avg',
                'volume_change', 'volume_moving_avg',
                'is_cs2', 'is_maplestory'
            ]
            
            X = final_df[feature_columns]
            y = final_df['price']
            
            logging.info(f"Created features with shape: {X.shape}")
            return X, y
            
        except Exception as e:
            logging.error(f"Error creating features: {str(e)}")
            return None, None

    def train_model(self):
        """Train the price prediction model"""
        try:
            # Load and prepare data
            df = self.load_data()
            if df is None:
                return False
                
            X, y = self.create_features(df)
            if X is None or y is None:
                return False
            
            # Split data into training and testing sets
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
            
            # Scale features
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Initialize and train model
            self.model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            )
            
            self.model.fit(X_train_scaled, y_train)
            
            # Evaluate model
            y_pred = self.model.predict(X_test_scaled)
            mse = mean_squared_error(y_test, y_pred)
            r2 = r2_score(y_test, y_pred)
            
            logging.info(f"Model trained successfully")
            logging.info(f"Mean Squared Error: {mse:.2f}")
            logging.info(f"R2 Score: {r2:.2f}")
            
            # Save model and scaler
            joblib.dump(self.model, 'price_prediction_model.joblib')
            joblib.dump(self.scaler, 'price_prediction_scaler.joblib')
            
            return True
            
        except Exception as e:
            logging.error(f"Error training model: {str(e)}")
            return False

    def predict_price(self, features):
        """Predict price for new data"""
        try:
            if self.model is None:
                # Load saved model if not already loaded
                self.model = joblib.load('price_prediction_model.joblib')
                self.scaler = joblib.load('price_prediction_scaler.joblib')
            
            # Scale features
            features_scaled = self.scaler.transform(features)
            
            # Make prediction
            prediction = self.model.predict(features_scaled)
            
            return prediction
            
        except Exception as e:
            logging.error(f"Error making prediction: {str(e)}")
            return None

if __name__ == "__main__":
    predictor = PricePredictor()
    predictor.train_model() 