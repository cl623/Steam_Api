"""
Quick analysis of prediction accuracy using the trained model.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
import pandas as pd
from ml.price_predictor import PricePredictor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def analyze_predictions():
    """Analyze prediction accuracy."""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'market_data.db')
    predictor = PricePredictor(db_path=db_path)
    
    # Try to load existing model
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
    if predictor.load_models(path=models_dir):
        logging.info("Loaded existing model")
    else:
        logging.info("No existing model found, training with 50 items...")
        predictor.train_model('730', max_items=50)
        predictor.save_models(path=models_dir)
    
    # Prepare test data
    logging.info("Preparing test data...")
    X, y, item_names = predictor.prepare_data('730', max_items=50)
    
    if X is None:
        logging.error("No data available")
        return
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    item_names_train, item_names_test = train_test_split(item_names, test_size=0.2, random_state=42)
    
    # Scale features
    scaler = predictor.scalers['730']
    X_test_scaled = scaler.transform(X_test)
    
    # Make predictions
    model = predictor.models['730']
    y_pred = model.predict(X_test_scaled)
    
    # Calculate metrics
    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    # Percentage errors
    percentage_errors = np.abs((y_test - y_pred) / y_test) * 100
    mape = np.mean(percentage_errors)
    median_ape = np.median(percentage_errors)
    
    logging.info(f"\n{'='*80}")
    logging.info(f"PREDICTION ACCURACY ANALYSIS")
    logging.info(f"{'='*80}\n")
    
    logging.info(f"Overall Metrics:")
    logging.info(f"  R² Score: {r2:.4f} ({r2*100:.2f}% variance explained)")
    logging.info(f"  RMSE: ${rmse:.2f}")
    logging.info(f"  MAE: ${mae:.2f}")
    logging.info(f"  MAPE: {mape:.2f}%")
    logging.info(f"  Median APE: {median_ape:.2f}%")
    
    # Error distribution
    errors = y_pred - y_test
    logging.info(f"\nError Distribution:")
    logging.info(f"  Mean error: ${np.mean(errors):.2f} (positive = overprediction)")
    logging.info(f"  Std error: ${np.std(errors):.2f}")
    logging.info(f"  Min error: ${np.min(errors):.2f}")
    logging.info(f"  Max error: ${np.max(errors):.2f}")
    
    # Price range analysis
    price_ranges = [
        (0, 1, "Under $1"),
        (1, 5, "$1-$5"),
        (5, 10, "$5-$10"),
        (10, 25, "$10-$25"),
        (25, 50, "$25-$50"),
        (50, 100, "$50-$100"),
        (100, float('inf'), "Over $100")
    ]
    
    logging.info(f"\nPerformance by Price Range:")
    logging.info(f"{'Range':<15} {'Samples':>8} {'MAE':>10} {'MAPE':>10} {'R²':>10}")
    logging.info(f"{'-'*55}")
    
    for min_price, max_price, label in price_ranges:
        mask = (y_test >= min_price) & (y_test < max_price)
        if mask.sum() > 0:
            range_mae = mean_absolute_error(y_test[mask], y_pred[mask])
            range_mape = np.mean(np.abs((y_test[mask] - y_pred[mask]) / y_test[mask])) * 100
            range_r2 = r2_score(y_test[mask], y_pred[mask])
            logging.info(f"{label:<15} {mask.sum():>8} ${range_mae:>9.2f} {range_mape:>9.1f}% {range_r2:>9.4f}")
    
    # Sample predictions
    logging.info(f"\nSample Predictions (First 15):")
    logging.info(f"{'Item Name':<45} {'Actual':>10} {'Predicted':>10} {'Error':>10} {'Error %':>10}")
    logging.info(f"{'-'*85}")
    
    for i in range(min(15, len(y_test))):
        item_name = item_names_test[i][:43] + "..." if len(item_names_test[i]) > 46 else item_names_test[i]
        actual = y_test[i]
        predicted = y_pred[i]
        error = predicted - actual
        error_pct = (error / actual) * 100 if actual > 0 else 0
        logging.info(f"{item_name:<45} ${actual:>9.2f} ${predicted:>9.2f} ${error:>9.2f} {error_pct:>9.1f}%")
    
    # Worst predictions
    abs_errors = np.abs(errors)
    worst_indices = np.argsort(abs_errors)[-10:][::-1]
    
    logging.info(f"\nWorst 10 Predictions (by absolute error):")
    logging.info(f"{'Item Name':<45} {'Actual':>10} {'Predicted':>10} {'Error':>10} {'Error %':>10}")
    logging.info(f"{'-'*85}")
    
    for idx in worst_indices:
        item_name = item_names_test[idx][:43] + "..." if len(item_names_test[idx]) > 46 else item_names_test[idx]
        actual = y_test[idx]
        predicted = y_pred[idx]
        error = predicted - actual
        error_pct = (error / actual) * 100 if actual > 0 else 0
        logging.info(f"{item_name:<45} ${actual:>9.2f} ${predicted:>9.2f} ${error:>9.2f} {error_pct:>9.1f}%")
    
    # Best predictions
    best_indices = np.argsort(abs_errors)[:10]
    
    logging.info(f"\nBest 10 Predictions (by absolute error):")
    logging.info(f"{'Item Name':<45} {'Actual':>10} {'Predicted':>10} {'Error':>10} {'Error %':>10}")
    logging.info(f"{'-'*85}")
    
    for idx in best_indices:
        item_name = item_names_test[idx][:43] + "..." if len(item_names_test[idx]) > 46 else item_names_test[idx]
        actual = y_test[idx]
        predicted = y_pred[idx]
        error = predicted - actual
        error_pct = (error / actual) * 100 if actual > 0 else 0
        logging.info(f"{item_name:<45} ${actual:>9.2f} ${predicted:>9.2f} ${error:>9.2f} {error_pct:>9.1f}%")
    
    # Analyze why simple predictions fail
    logging.info(f"\n{'='*80}")
    logging.info(f"ANALYSIS: Why Simple Predictions Fail")
    logging.info(f"{'='*80}\n")
    
    logging.info("The test predictions in train_model.py use simplified inputs:")
    logging.info("  - Only current_price and current_volume")
    logging.info("  - Moving averages default to current_price")
    logging.info("  - This doesn't match the training data format\n")
    
    logging.info("Training data uses:")
    logging.info("  - Actual 7-day and 30-day moving averages")
    logging.info("  - Actual price volatility (std7)")
    logging.info("  - Historical volume patterns\n")
    
    logging.info("To get accurate predictions, you need to:")
    logging.info("  1. Calculate actual moving averages from price history")
    logging.info("  2. Use real volatility measurements")
    logging.info("  3. Provide proper volume moving averages\n")
    
    # Show feature importance
    feature_importance = model.feature_importances_
    feature_names = [
        'price', 'price_ma7', 'price_ma30', 'price_std7', 'volume_ma7',
        'type_weapon_skin', 'type_sticker', 'type_case', 'type_agent', 'type_gloves',
        'type_knife', 'type_other', 'is_weapon_skin', 'condition_quality',
        'is_stattrak', 'is_souvenir', 'has_sticker', 'is_case', 'is_sticker',
        'is_agent', 'is_gloves', 'is_knife'
    ]
    
    logging.info(f"Top 10 Most Important Features:")
    top_indices = np.argsort(feature_importance)[-10:][::-1]
    for idx in top_indices:
        logging.info(f"  {feature_names[idx]:20s}: {feature_importance[idx]:.4f} ({feature_importance[idx]*100:.2f}%)")

if __name__ == '__main__':
    analyze_predictions()
