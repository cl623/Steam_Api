#!/usr/bin/env python3
"""
Steam Market Data Collector
Continuously collects price history data from Steam Community Market
"""

import sys
import os
import argparse
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.market_collector import SteamMarketCollector
import time
import signal

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    print("\n" + "=" * 60)
    print("Graceful shutdown initiated...")
    print("=" * 60)
    if 'collector' in globals():
        collector.stop_event.set()
        print("Stop signal sent to collector")
        print("Waiting for workers to finish current operations...")
        # Give threads time to finish
        import time
        time.sleep(2)
    print("Exiting...")
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Steam Market Data Collector - Continuously collects CS2 price history data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with defaults (3 workers, 12-hour update interval, uses app/config.py cookies)
  python scripts/run_collector.py
  
  # Run with 4 workers for faster collection
  python scripts/run_collector.py --workers 4
  
  # Run with custom database path
  python scripts/run_collector.py --db-path /path/to/market_data.db
  
  # Run with 6-hour update interval (more frequent updates)
  python scripts/run_collector.py --update-interval 6
  
  # Use cookie string (recommended - easiest method)
  python scripts/run_collector.py --cookie-string "sessionid=...; steamLoginSecure=...; ..."
  
  # Use environment variables for Steam cookies
  export STEAM_COOKIE_STRING="sessionid=...; steamLoginSecure=...; ..."
  python scripts/run_collector.py
  
  # Or use individual cookies
  export STEAM_SESSIONID=your_sessionid
  export STEAM_LOGIN_SECURE=your_login_secure
  python scripts/run_collector.py
        """
    )
    
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=3,
        help='Number of worker threads (default: 3, recommended: 2-4)'
    )
    
    parser.add_argument(
        '--db-path', '-d',
        type=str,
        default=None,
        help='Path to database file (default: data/market_data.db)'
    )
    
    parser.add_argument(
        '--update-interval', '-i',
        type=int,
        default=12,
        help='Update interval in hours (default: 12, how often to refresh price history)'
    )
    
    parser.add_argument(
        '--sessionid',
        type=str,
        default=None,
        help='Steam sessionid cookie (overrides environment variable and defaults)'
    )
    
    parser.add_argument(
        '--steam-login-secure',
        type=str,
        default=None,
        help='Steam steamLoginSecure cookie (overrides environment variable and defaults)'
    )
    
    parser.add_argument(
        '--cookie-string',
        type=str,
        default=None,
        help='Full cookie string from browser (will parse all cookies, overrides other cookie options)'
    )
    
    parser.add_argument(
        '--pause-file',
        type=str,
        default=None,
        help='Path to pause file (create this file to pause collection, delete to resume). Default: pause_collector.txt'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.workers < 1 or args.workers > 10:
        print("Error: Number of workers must be between 1 and 10")
        print("Recommended: 2-4 workers (rate limit is 8 requests/minute)")
        sys.exit(1)
    
    if args.update_interval < 1:
        print("Error: Update interval must be at least 1 hour")
        sys.exit(1)
    
    # Prepare Steam cookies if provided
    steam_cookies = None
    if args.cookie_string:
        # Parse cookie string (same logic as web app)
        try:
            from app.utils import parse_cookie_string
        except ImportError:
            # Fallback if utils not available
            def parse_cookie_string(cookie_string):
                cookies = {}
                for cookie_pair in cookie_string.split('; '):
                    if '=' in cookie_pair:
                        name, value = cookie_pair.split('=', 1)
                        cookies[name.strip()] = value.strip()
                return cookies
        
        steam_cookies = parse_cookie_string(args.cookie_string)
        if not steam_cookies.get('sessionid') or not steam_cookies.get('steamLoginSecure'):
            print("Error: Cookie string must contain sessionid and steamLoginSecure")
            sys.exit(1)
        print("Using cookies from --cookie-string")
    elif args.sessionid or args.steam_login_secure:
        if not args.sessionid or not args.steam_login_secure:
            print("Error: Both --sessionid and --steam-login-secure must be provided together")
            sys.exit(1)
        steam_cookies = {
            'sessionid': args.sessionid,
            'steamLoginSecure': args.steam_login_secure
        }
        print("Using cookies from command-line arguments")
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize the collector
    # Determine pause file path
    pause_file = args.pause_file if args.pause_file else 'pause_collector.txt'
    enable_pause = args.pause_file is not None or os.path.exists(pause_file)
    
    print("=" * 60)
    print("Steam Market Data Collector")
    print("=" * 60)
    print(f"Workers: {args.workers}")
    print(f"Update Interval: {args.update_interval} hours")
    print(f"Database: {args.db_path or 'data/market_data.db (default)'}")
    print(f"Steam Cookies: {'Custom' if steam_cookies else 'Environment/Default'}")
    if enable_pause:
        print(f"Pause enabled: Create '{pause_file}' to pause, delete to resume")
    print("=" * 60)
    print("Starting collection...")
    print("Press Ctrl+C to stop gracefully")
    print("=" * 60)
    
    collector = SteamMarketCollector(
        db_path=args.db_path,
        steam_cookies=steam_cookies,
        update_interval_hours=args.update_interval,
        pause_file=pause_file if enable_pause else None
    )
    
    try:
        collector.start_collection(num_workers=args.workers)
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("Keyboard interrupt received")
        print("=" * 60)
        collector.stop_event.set()
        print("Waiting for graceful shutdown...")
        import time
        time.sleep(3)  # Give threads time to finish
        print("Shutdown complete")
    except Exception as e:
        print(f"\n" + "=" * 60)
        print(f"Fatal error: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        collector.stop_event.set()
        print("Initiating graceful shutdown...")
        import time
        time.sleep(2)
        sys.exit(1) 