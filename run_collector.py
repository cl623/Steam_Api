from market_data_collector import MarketDataCollector
import time
import signal
import sys

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    print("\nShutting down collector...")
    collector.cleanup()
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize the collector
    print("Starting Steam Market Data Collector...")
    collector = MarketDataCollector(db_path='market_data.db')
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt, shutting down...")
        collector.cleanup() 