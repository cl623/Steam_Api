"""
Detailed model evaluation script to investigate prediction accuracy.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
import pandas as pd
from ml.price_predictor import PricePredictor
import logging
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('model_evaluation.log'),
        logging.StreamHandler()
    ]
)

def evaluate_model_detailed(predictor, game_id, max_items=50):
    """Perform detailed evaluation of the model."""
    logging.info(f"\n{'='*80}")
    logging.info(f"Detailed Model Evaluation for game {game_id}")
    logging.info(f"{'='*80}\n")
    
    # Prepare data
    X, y, item_names = predictor.prepare_data(game_id, max_items=max_items)
    
    if X is None or len(X) == 0:
        logging.error("No data available for evaluation")
        return
    
    # Split data
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    item_names_train, item_names_test = train_test_split(item_names, test_size=0.2, random_state=42)
    
    # Scale features
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Load or train model
    if game_id not in predictor.models:
        logging.info("Model not found, training...")
        predictor.train_model(game_id, max_items=max_items)
    
    if game_id not in predictor.models:
        logging.error("Failed to get model")
        return
    
    model = predictor.models[game_id]
    
    # Make predictions
    y_pred = model.predict(X_test_scaled)
    
    # Overall metrics
    mse = mean_squared_error(y_test, y_pred)
    rmse = np.sqrt(mse)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    logging.info(f"Overall Performance:")
    logging.info(f"  MSE: {mse:.4f}")
    logging.info(f"  RMSE: ${rmse:.4f}")
    logging.info(f"  MAE: ${mae:.4f}")
    logging.info(f"  R²: {r2:.4f}")
    
    # Calculate percentage errors
    percentage_errors = np.abs((y_test - y_pred) / y_test) * 100
    mean_percentage_error = np.mean(percentage_errors)
    median_percentage_error = np.median(percentage_errors)
    
    logging.info(f"\nPercentage Error Analysis:")
    logging.info(f"  Mean Absolute Percentage Error (MAPE): {mean_percentage_error:.2f}%")
    logging.info(f"  Median Absolute Percentage Error: {median_percentage_error:.2f}%")
    
    # Error distribution
    logging.info(f"\nError Distribution:")
    logging.info(f"  Min error: ${np.min(y_test - y_pred):.2f}")
    logging.info(f"  Max error: ${np.max(y_test - y_pred):.2f}")
    logging.info(f"  Mean error: ${np.mean(y_test - y_pred):.2f}")
    logging.info(f"  Std error: ${np.std(y_test - y_pred):.2f}")
    
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
    for min_price, max_price, label in price_ranges:
        mask = (y_test >= min_price) & (y_test < max_price)
        if mask.sum() > 0:
            range_mae = mean_absolute_error(y_test[mask], y_pred[mask])
            range_mape = np.mean(np.abs((y_test[mask] - y_pred[mask]) / y_test[mask])) * 100
            logging.info(f"  {label:15s}: {mask.sum():5d} samples, MAE=${range_mae:.2f}, MAPE={range_mape:.1f}%")
    
    # Sample predictions with details
    logging.info(f"\nSample Predictions (First 20 test samples):")
    logging.info(f"{'Item Name':<50} {'Actual':>10} {'Predicted':>10} {'Error':>10} {'Error %':>10}")
    logging.info(f"{'-'*90}")
    
    for i in range(min(20, len(y_test))):
        item_name = item_names_test[i][:47] + "..." if len(item_names_test[i]) > 50 else item_names_test[i]
        actual = y_test[i]
        predicted = y_pred[i]
        error = predicted - actual
        error_pct = (error / actual) * 100 if actual > 0 else 0
        logging.info(f"{item_name:<50} ${actual:>9.2f} ${predicted:>9.2f} ${error:>9.2f} {error_pct:>9.1f}%")
    
    # Worst predictions
    errors = np.abs(y_test - y_pred)
    worst_indices = np.argsort(errors)[-10:][::-1]
    
    logging.info(f"\nWorst 10 Predictions (by absolute error):")
    logging.info(f"{'Item Name':<50} {'Actual':>10} {'Predicted':>10} {'Error':>10} {'Error %':>10}")
    logging.info(f"{'-'*90}")
    
    for idx in worst_indices:
        item_name = item_names_test[idx][:47] + "..." if len(item_names_test[idx]) > 50 else item_names_test[idx]
        actual = y_test[idx]
        predicted = y_pred[idx]
        error = predicted - actual
        error_pct = (error / actual) * 100 if actual > 0 else 0
        logging.info(f"{item_name:<50} ${actual:>9.2f} ${predicted:>9.2f} ${error:>9.2f} {error_pct:>9.1f}%")
    
    # Best predictions
    best_indices = np.argsort(errors)[:10]
    
    logging.info(f"\nBest 10 Predictions (by absolute error):")
    logging.info(f"{'Item Name':<50} {'Actual':>10} {'Predicted':>10} {'Error':>10} {'Error %':>10}")
    logging.info(f"{'-'*90}")
    
    for idx in best_indices:
        item_name = item_names_test[idx][:47] + "..." if len(item_names_test[idx]) > 50 else item_names_test[idx]
        actual = y_test[idx]
        predicted = y_pred[idx]
        error = predicted - actual
        error_pct = (error / actual) * 100 if actual > 0 else 0
        logging.info(f"{item_name:<50} ${actual:>9.2f} ${predicted:>9.2f} ${error:>9.2f} {error_pct:>9.1f}%")
    
    # Analyze by item type
    from ml.feature_extractor import ItemFeatureExtractor
    extractor = ItemFeatureExtractor()
    
    item_types = {}
    for item_name in item_names_test:
        features = extractor.extract_features(item_name)
        item_type = features['item_type']
        if item_type not in item_types:
            item_types[item_type] = []
        item_types[item_type].append(item_name)
    
    logging.info(f"\nPerformance by Item Type:")
    for item_type, type_items in item_types.items():
        type_indices = [i for i, name in enumerate(item_names_test) if name in type_items]
        if len(type_indices) > 0:
            type_mae = mean_absolute_error(y_test[type_indices], y_pred[type_indices])
            type_mape = np.mean(np.abs((y_test[type_indices] - y_pred[type_indices]) / y_test[type_indices])) * 100
            logging.info(f"  {item_type:20s}: {len(type_indices):5d} samples, MAE=${type_mae:.2f}, MAPE={type_mape:.1f}%")

def main():
    """Main evaluation function."""
    import argparse
    parser = argparse.ArgumentParser(description='Evaluate model accuracy')
    parser.add_argument('--max-items', type=int, default=50, help='Number of items to use (default: 50)')
    parser.add_argument('--game-id', type=str, default='730', help='Game ID (default: 730)')
    
    args = parser.parse_args()
    
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'market_data.db')
    predictor = PricePredictor(db_path=db_path)
    
    evaluate_model_detailed(predictor, args.game_id, max_items=args.max_items)

if __name__ == '__main__':
    main()
