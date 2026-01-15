"""
Script to train the price prediction model with parsed item features.

Usage:
    python scripts/train_model.py                    # Full mode (all items)
    python scripts/train_model.py --mode sample     # Sample mode (50 items)
    python scripts/train_model.py --mode full        # Full mode (all items)
    python scripts/train_model.py --max-items 100    # Custom sample size
    python scripts/train_model.py --pause-file pause.txt  # Enable pause/resume

Pause/Resume:
    - Create file 'pause.txt' to pause training (will pause after current item)
    - Delete 'pause.txt' to resume training
    - Press Ctrl+C to stop and save progress
"""
import sys
import os
import argparse
import signal
import threading

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from ml.price_predictor import PricePredictor
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('price_prediction.log'),
        logging.StreamHandler()
    ]
)

def check_data_availability(db_path):
    """Check how much data is available for training."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Count items
        cursor.execute('SELECT COUNT(*) FROM items WHERE game_id = ?', ('730',))
        item_count = cursor.fetchone()[0]
        
        # Count price history entries
        cursor.execute('''
            SELECT COUNT(*) 
            FROM price_history ph 
            JOIN items i ON ph.item_id = i.id 
            WHERE i.game_id = ?
        ''', ('730',))
        history_count = cursor.fetchone()[0]
        
        # Count items with sufficient history (at least 14 days for 7 lookback + 7 prediction)
        cursor.execute('''
            SELECT COUNT(*)
            FROM (
                SELECT i.id
                FROM items i
                JOIN price_history ph ON i.id = ph.item_id
                WHERE i.game_id = ?
                GROUP BY i.id
                HAVING COUNT(ph.id) >= 14
            )
        ''', ('730',))
        result = cursor.fetchone()
        sufficient_data_count = result[0] if result else 0
        
        # Get distribution info
        cursor.execute('''
            SELECT 
                MIN(cnt) as min_count,
                MAX(cnt) as max_count,
                AVG(cnt) as avg_count,
                COUNT(*) as items_with_data
            FROM (
                SELECT i.id, COUNT(ph.id) as cnt
                FROM items i
                LEFT JOIN price_history ph ON i.id = ph.item_id
                WHERE i.game_id = ?
                GROUP BY i.id
            )
        ''', ('730',))
        dist = cursor.fetchone()
        if dist:
            logging.info(f"  Price history distribution:")
            logging.info(f"    Min entries per item: {dist[0]}")
            logging.info(f"    Max entries per item: {dist[1]}")
            logging.info(f"    Avg entries per item: {dist[2]:.1f}")
            logging.info(f"    Items with any data: {dist[3]}")
        
        logging.info(f"Data availability for CS2 (game_id=730):")
        logging.info(f"  Total items: {item_count}")
        logging.info(f"  Total price history entries: {history_count}")
        logging.info(f"  Items with sufficient data (>=14 entries): {sufficient_data_count}")
        
        return item_count, history_count, sufficient_data_count

class PausableTrainer:
    """Wrapper to add pause/resume functionality to training."""
    
    def __init__(self, pause_file='pause.txt'):
        self.pause_file = pause_file
        self.paused = False
        self.stop_requested = False
        self.pause_lock = threading.Lock()
        
    def check_pause(self):
        """Check if pause file exists and pause if needed. Returns True if paused."""
        if not os.path.exists(self.pause_file):
            # Not paused
            if self.paused:
                # Was paused, now resumed
                with self.pause_lock:
                    self.paused = False
                    logging.info(f"\n{'='*80}")
                    logging.info("RESUMING: Training resumed")
                    logging.info(f"{'='*80}\n")
            return False
        
        # Pause file exists
        with self.pause_lock:
            if not self.paused:
                self.paused = True
                logging.info(f"\n{'='*80}")
                logging.info("PAUSE DETECTED: Training paused")
                logging.info(f"Delete '{self.pause_file}' to resume training")
                logging.info(f"{'='*80}\n")
        
        # Wait until pause file is removed
        while os.path.exists(self.pause_file) and not self.stop_requested:
            time.sleep(1)
        
        if not self.stop_requested:
            with self.pause_lock:
                self.paused = False
                logging.info(f"\n{'='*80}")
                logging.info("RESUMING: Training resumed")
                logging.info(f"{'='*80}\n")
        
        return self.paused
    
    def request_stop(self):
        """Request training to stop."""
        self.stop_requested = True

def main():
    """Main training function."""
    parser = argparse.ArgumentParser(
        description='Train price prediction model',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/train_model.py                    # Full mode
  python scripts/train_model.py --mode sample       # Sample mode (50 items)
  python scripts/train_model.py --mode full         # Full mode
  python scripts/train_model.py --max-items 100      # Custom sample size
        """
    )
    parser.add_argument(
        '--mode',
        choices=['sample', 'full'],
        default='full',
        help='Training mode: sample (50 items) or full (all items)'
    )
    parser.add_argument(
        '--max-items',
        type=int,
        default=None,
        help='Maximum number of items to process (overrides --mode)'
    )
    parser.add_argument(
        '--pause-file',
        type=str,
        default=None,
        help='Path to pause file (create this file to pause, delete to resume). Default: pause.txt in current directory'
    )
    
    args = parser.parse_args()
    
    # Initialize pause functionality (enabled by default if pause file exists, or if explicitly requested)
    pause_file = args.pause_file if args.pause_file else 'pause.txt'
    enable_pause = args.pause_file is not None or os.path.exists(pause_file)
    trainer = PausableTrainer(pause_file=pause_file) if enable_pause else None
    
    # Signal handler for graceful shutdown
    def signal_handler(signum, frame):
        logging.info("\n" + "="*80)
        logging.info("Shutdown signal received. Saving progress...")
        logging.info("="*80)
        if trainer:
            trainer.request_stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Determine max_items based on arguments
    if args.max_items is not None:
        max_items = args.max_items
        mode_str = f"custom ({max_items} items)"
    elif args.mode == 'sample':
        max_items = 50
        mode_str = "sample (50 items)"
    else:
        max_items = None
        mode_str = "full (all items)"
    
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'market_data.db')
    
    # Check data availability
    item_count, history_count, sufficient_data = check_data_availability(db_path)
    
    if sufficient_data == 0:
        logging.error("No items with sufficient data for training. Need at least 14 price history entries per item.")
        return
    
    # Initialize predictor
    predictor = PricePredictor(db_path=db_path)
    
    # Train model for CS2
    game_id = '730'
    logging.info(f"\n{'='*80}")
    logging.info(f"Training model for game {game_id} (Counter-Strike 2)")
    logging.info(f"Mode: {mode_str}")
    if trainer:
        logging.info(f"Pause enabled: Create '{pause_file}' to pause, delete to resume")
        logging.info(f"Press Ctrl+C to stop and save progress")
    logging.info(f"{'='*80}\n")
    
    # Create pause check function if pause is enabled
    pause_check_fn = None
    if trainer:
        pause_check_fn = lambda: trainer.check_pause()
    
    success = predictor.train_model(game_id, max_items=max_items, pause_check=pause_check_fn)
    
    if success:
        # Save models
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
        predictor.save_models(path=models_dir)
        logging.info(f"\nModel saved to {models_dir}")
        
        # Test prediction
        # IMPROVED: Now uses auto_calculate_ma=True by default to get accurate predictions
        logging.info("\nTesting prediction with sample items...")
        logging.info("Using auto-calculated moving averages from database for accuracy")
        test_items = [
            "AK-47 | Redline (Field-Tested)",
            "Operation Breakout Weapon Case",
            "AK-47 | Aquamarine Revenge (Minimal Wear)",
        ]
        
        for item_name in test_items:
            # Auto-calculates MAs from database - much more accurate!
            prediction = predictor.predict_price(game_id, item_name, auto_calculate_ma=True)
            if prediction:
                # Get current price for display
                ma_data = predictor.get_moving_averages_from_db(item_name, game_id)
                if ma_data:
                    current_price = ma_data['current_price']
                    logging.info(f"  {item_name}: Current=${current_price:.2f}, Predicted=${prediction:.2f}")
                else:
                    logging.info(f"  {item_name}: Predicted=${prediction:.2f}")
    else:
        logging.error("Model training failed!")

if __name__ == '__main__':
    main()
