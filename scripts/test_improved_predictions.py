"""Test the improved prediction accuracy with auto-calculated moving averages."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.price_predictor import PricePredictor
import logging

logging.basicConfig(level=logging.INFO)

def main():
    predictor = PricePredictor()
    
    # Load existing model
    if not predictor.load_models():
        print("No model found, training...")
        predictor.train_model('730', max_items=50)
        predictor.save_models()
    
    # Test items from database
    test_items = [
        'Operation Bravo Case',
        'AK-47 | Redline (Field-Tested)',
        'AK-47 | Aquamarine Revenge (Minimal Wear)',
    ]
    
    print("\n" + "="*80)
    print("TESTING IMPROVED PREDICTIONS WITH AUTO-CALCULATED MOVING AVERAGES")
    print("="*80 + "\n")
    
    for item_name in test_items:
        print(f"\nItem: {item_name}")
        print("-" * 80)
        
        # Get moving averages
        ma_data = predictor.get_moving_averages_from_db(item_name, '730')
        
        if ma_data:
            print(f"Current Price: ${ma_data['current_price']:.2f}")
            print(f"7-day MA: ${ma_data['price_ma7']:.2f}")
            print(f"30-day MA: ${ma_data['price_ma30']:.2f}")
            print(f"7-day Std: ${ma_data['price_std7']:.2f}")
            print(f"7-day Volume MA: {ma_data['volume_ma7']:.0f}")
            
            # Prediction with auto-calculated MAs (IMPROVED)
            prediction = predictor.predict_price('730', item_name, auto_calculate_ma=True)
            
            if prediction:
                error_pct = abs(prediction - ma_data['current_price']) / ma_data['current_price'] * 100
                print(f"\n[OK] Prediction (with auto MAs): ${prediction:.2f}")
                print(f"     Change from current: {error_pct:.1f}%")
            else:
                print("\n[FAIL] Prediction failed")
        else:
            print(f"[FAIL] Item not found in database or insufficient data")
            
            # Try prediction anyway (will use defaults)
            prediction = predictor.predict_price('730', item_name, current_price=10.0, current_volume=1000, auto_calculate_ma=False)
            if prediction:
                print(f"[WARN] Prediction (with defaults): ${prediction:.2f} (less accurate)")

if __name__ == '__main__':
    main()
