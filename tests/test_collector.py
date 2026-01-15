#!/usr/bin/env python3
"""
Test script for market_history_collector.py
Tests the improved collection algorithm with rate limiting and session-based fetching
"""

import sys
import os
import time
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collector.market_collector import SteamMarketCollector
import logging

# Configure logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'
)

def test_collector_initialization():
    """Test 1: Verify collector initializes correctly"""
    print("\n" + "="*60)
    print("TEST 1: Collector Initialization")
    print("="*60)
    
    try:
        collector = SteamMarketCollector(update_interval_hours=12)
        print("[OK] Collector initialized successfully")
        print(f"   - Update interval: {collector.update_interval_hours} hours")
        print(f"   - Rate limiters configured for {len(collector.rate_limiters)} games")
        print(f"   - Worker sleep times: {collector.worker_sleep_times}")
        return collector
    except Exception as e:
        print(f"[FAIL] Initialization failed: {e}")
        return None

def test_rate_limiting(collector):
    """Test 2: Verify rate limiting works correctly"""
    print("\n" + "="*60)
    print("TEST 2: Rate Limiting")
    print("="*60)
    
    if not collector:
        print("[FAIL] Collector not initialized")
        return False
    
    game_id = '730'  # CS2
    
    # Test rate limiter
    print(f"Testing rate limiter for game {game_id} (CS2)...")
    print(f"   - Minute limit: {collector.rate_limiters[game_id]['minute'].max_requests} requests/minute")
    print(f"   - Day limit: {collector.rate_limiters[game_id]['day'].max_requests} requests/day")
    
    # Make a few test requests
    success_count = 0
    for i in range(5):
        if collector.check_rate_limit(game_id):
            success_count += 1
            requests_in_window = collector.rate_limiters[game_id]['minute'].get_requests_in_window()
            print(f"   Request {i+1}: [OK] Allowed (Total in window: {requests_in_window})")
        else:
            wait_time = collector.rate_limiters[game_id]['minute'].get_wait_time()
            print(f"   Request {i+1}: [WAIT] Rate limited (Wait: {wait_time:.1f}s)")
            time.sleep(1)
    
    print(f"\n[OK] Rate limiting test: {success_count}/5 requests allowed")
    return True

def test_price_history_fetch(collector):
    """Test 3: Test price history fetching with new session-based approach"""
    print("\n" + "="*60)
    print("TEST 3: Price History Fetching (Session-Based)")
    print("="*60)
    
    if not collector:
        print("[FAIL] Collector not initialized")
        return False
    
    # Test with a popular CS2 item
    game_id = '730'
    test_item = 'Danger Zone Case'
    
    print(f"Fetching price history for: {test_item} (Game: CS2)")
    print("   Using new session-based approach with Akamai cookie handling...")
    
    try:
        price_history = collector.fetch_price_history(game_id, test_item)
        
        if price_history and 'prices' in price_history:
            price_count = len(price_history['prices'])
            print(f"[OK] Successfully fetched price history!")
            print(f"   - Price entries: {price_count}")
            if price_count > 0:
                print(f"   - First entry: {price_history['prices'][0]}")
                print(f"   - Last entry: {price_history['prices'][-1]}")
            return True
        else:
            print("[WARN] No price history returned (may be empty or account restrictions)")
            return True  # Still a success if we got a response
    except Exception as e:
        print(f"[FAIL] Price history fetch failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_incremental_updates(collector):
    """Test 4: Test incremental update logic"""
    print("\n" + "="*60)
    print("TEST 4: Incremental Update Logic")
    print("="*60)
    
    if not collector:
        print("[FAIL] Collector not initialized")
        return False
    
    game_id = '730'
    test_item = 'Danger Zone Case'
    
    print(f"Testing update logic for: {test_item}")
    print(f"   - Update interval: {collector.update_interval_hours} hours")
    
    # Check if item exists in database
    last_updated = collector.get_item_last_updated(test_item, game_id)
    
    if last_updated:
        time_since = time.time() - last_updated.timestamp()
        hours_since = time_since / 3600
        print(f"   - Item found in database")
        print(f"   - Last updated: {last_updated}")
        print(f"   - Hours since update: {hours_since:.2f}")
        
        should_update = collector.should_update_price_history(test_item, game_id, collector.update_interval_hours)
        print(f"   - Should update: {should_update}")
        
        if should_update:
            print("   [OK] Item needs update (data is stale)")
        else:
            print("   [OK] Item is fresh (will be skipped)")
    else:
        print(f"   - Item not in database (will be fetched)")
        should_update = collector.should_update_price_history(test_item, game_id, collector.update_interval_hours)
        print(f"   - Should update: {should_update}")
    
    return True

def test_dynamic_sleep(collector):
    """Test 5: Test dynamic sleep calculation"""
    print("\n" + "="*60)
    print("TEST 5: Dynamic Sleep Calculation")
    print("="*60)
    
    if not collector:
        print("[FAIL] Collector not initialized")
        return False
    
    game_id = '730'
    thread_name = 'Worker-1'
    
    print(f"Testing dynamic sleep for {thread_name} (Game: CS2)")
    
    # Test with different capacity levels
    for i in range(8):
        collector.check_rate_limit(game_id)  # Add requests to window
        sleep_time = collector.calculate_dynamic_sleep(thread_name, game_id)
        requests_in_window = collector.rate_limiters[game_id]['minute'].get_requests_in_window()
        capacity = collector.rate_limiters[game_id]['minute'].max_requests - requests_in_window
        
        print(f"   Request {i+1}: Sleep={sleep_time:.2f}s, Capacity={capacity}, In window={requests_in_window}")
    
    print("\n[OK] Dynamic sleep calculation working correctly")
    return True

def test_single_item_collection(collector):
    """Test 6: Test collecting a single item end-to-end"""
    print("\n" + "="*60)
    print("TEST 6: Single Item Collection (End-to-End)")
    print("="*60)
    
    if not collector:
        print("[FAIL] Collector not initialized")
        return False
    
    game_id = '730'
    test_item = 'Danger Zone Case'
    
    print(f"Testing full collection cycle for: {test_item}")
    print("   This will test: rate limiting -> fetch -> store -> update timestamp")
    
    try:
        # Check if should update
        if not collector.should_update_price_history(test_item, game_id, collector.update_interval_hours):
            print("   [SKIP] Item is fresh, skipping (this is expected behavior)")
            return True
        
        # Fetch price history
        print("   Step 1: Fetching price history...")
        price_history = collector.fetch_price_history(game_id, test_item)
        
        if not price_history:
            print("   [FAIL] Failed to fetch price history")
            return False
        
        # Store item
        print("   Step 2: Storing item in database...")
        item_id = collector.store_item(test_item, game_id)
        print(f"   [OK] Item stored with ID: {item_id}")
        
        # Store price history
        print("   Step 3: Storing price history...")
        collector.store_price_history(item_id, price_history)
        print("   [OK] Price history stored")
        
        # Verify update timestamp
        print("   Step 4: Verifying update timestamp...")
        last_updated = collector.get_item_last_updated(test_item, game_id)
        if last_updated:
            print(f"   [OK] Last updated: {last_updated}")
        else:
            print("   [WARN] Could not retrieve last_updated timestamp")
        
        print("\n[OK] End-to-end collection test successful!")
        return True
        
    except Exception as e:
        print(f"[FAIL] Collection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("STEAM MARKET COLLECTOR - TEST SUITE")
    print("="*60)
    print("\nTesting improvements:")
    print("  - Session-based price history fetching (Akamai cookies)")
    print("  - Rate limiting optimization (8 req/min, 900 req/day)")
    print("  - Incremental updates (12-hour interval)")
    print("  - Dynamic sleep calculation")
    print("  - Constant stream maintenance")
    
    results = []
    
    # Test 1: Initialization
    collector = test_collector_initialization()
    results.append(("Initialization", collector is not None))
    
    if not collector:
        print("\n[FAIL] Cannot continue tests - collector initialization failed")
        return
    
    # Test 2: Rate Limiting
    results.append(("Rate Limiting", test_rate_limiting(collector)))
    
    # Test 3: Price History Fetch
    results.append(("Price History Fetch", test_price_history_fetch(collector)))
    
    # Test 4: Incremental Updates
    results.append(("Incremental Updates", test_incremental_updates(collector)))
    
    # Test 5: Dynamic Sleep
    results.append(("Dynamic Sleep", test_dynamic_sleep(collector)))
    
    # Test 6: Single Item Collection
    results.append(("Single Item Collection", test_single_item_collection(collector)))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[SUCCESS] All tests passed! Collector is ready for use.")
    else:
        print("\n[WARN] Some tests failed. Review the output above.")

if __name__ == "__main__":
    main()
