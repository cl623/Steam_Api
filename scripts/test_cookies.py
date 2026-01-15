#!/usr/bin/env python3
"""
Test script to validate Steam cookies for freshness and validity.

This script tests if your Steam sessionid and steamLoginSecure cookies are valid
and can successfully access Steam Community Market price history data.

Usage:
    python scripts/test_cookies.py
    
    # Or with command line arguments:
    python scripts/test_cookies.py --sessionid YOUR_SESSIONID --steam-login-secure YOUR_LOGIN_SECURE
    
    # Or with environment variables:
    export STEAM_SESSIONID=your_sessionid
    export STEAM_LOGIN_SECURE=your_steam_login_secure
    python scripts/test_cookies.py
"""

import sys
import os
import argparse
import requests
from urllib.parse import quote
import json
import re

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_cookie_string(cookie_string):
    """
    Parse a cookie string from browser's Cookie header.
    
    Args:
        cookie_string: Full cookie string from browser (e.g., "sessionid=abc; steamLoginSecure=xyz")
    
    Returns:
        dict: Dictionary of cookie name -> value pairs
    """
    cookies = {}
    for cookie in cookie_string.split('; '):
        if '=' in cookie:
            name, value = cookie.split('=', 1)
            cookies[name.strip()] = value.strip()
    return cookies


def test_cookies(sessionid, steamLoginSecure, browserid=None, steamCountry=None, webTradeEligibility=None, cookie_string=None):
    """
    Test Steam cookies by attempting to fetch price history data.
    
    Args:
        sessionid: Steam session ID cookie
        steamLoginSecure: Steam login secure cookie
        browserid: Optional browser ID cookie
        steamCountry: Optional steamCountry cookie
        webTradeEligibility: Optional webTradeEligibility cookie
        cookie_string: Optional full cookie string from browser (will parse and use all cookies)
    
    Returns:
        dict: Test results with 'valid', 'message', and optional 'error' keys
    """
    # If cookie_string is provided, parse it and extract all cookies
    all_cookies = {}
    if cookie_string:
        parsed_cookies = parse_cookie_string(cookie_string)
        all_cookies = parsed_cookies.copy()
        sessionid = parsed_cookies.get('sessionid', sessionid)
        steamLoginSecure = parsed_cookies.get('steamLoginSecure', steamLoginSecure)
        browserid = parsed_cookies.get('browserid', browserid)
        steamCountry = parsed_cookies.get('steamCountry', steamCountry)
        webTradeEligibility = parsed_cookies.get('webTradeEligibility', webTradeEligibility)
    else:
        all_cookies = {
            'sessionid': sessionid,
            'steamLoginSecure': steamLoginSecure,
        }
        if browserid:
            all_cookies['browserid'] = browserid
        if steamCountry:
            all_cookies['steamCountry'] = steamCountry
        if webTradeEligibility:
            all_cookies['webTradeEligibility'] = webTradeEligibility
    
    results = {
        'valid': False,
        'message': '',
        'error': None,
        'tests': {},
        'cookies': all_cookies  # Store all cookies for potential config update
    }
    
    # Validate input
    if not sessionid or not steamLoginSecure:
        results['error'] = 'Missing required cookies: sessionid and steamLoginSecure are required'
        results['message'] = '❌ Invalid: Missing required cookies'
        return results
    
    # Test 1: Basic cookie format validation
    print("[TEST] Testing cookie format...")
    if len(sessionid) < 10:
        results['error'] = 'sessionid appears to be too short or invalid'
        results['message'] = '[FAIL] Invalid: sessionid format appears incorrect'
        return results
    
    if not steamLoginSecure.startswith('7656119'):
        results['error'] = 'steamLoginSecure should start with Steam ID (7656119...)'
        results['message'] = '[FAIL] Invalid: steamLoginSecure format appears incorrect'
        return results
    
    results['tests']['format'] = True
    print("   [OK] Cookie format looks valid")
    
    # Test 2: Create session and set cookies
    print("\n[TEST] Testing session setup...")
    try:
        http_session = requests.Session()
        
        # Set cookies using requests' create_cookie helper for proper cookie creation
        from requests.cookies import create_cookie
        
        sessionid_cookie = create_cookie(
            name='sessionid',
            value=sessionid,
            domain='steamcommunity.com',
            path='/'
        )
        steamLoginSecure_cookie = create_cookie(
            name='steamLoginSecure',
            value=steamLoginSecure,
            domain='steamcommunity.com',
            path='/'
        )
        
        http_session.cookies.set_cookie(sessionid_cookie)
        http_session.cookies.set_cookie(steamLoginSecure_cookie)
        
        if browserid:
            browserid_cookie = create_cookie(
                name='browserid',
                value=browserid,
                domain='steamcommunity.com',
                path='/'
            )
            http_session.cookies.set_cookie(browserid_cookie)
        
        # Additional cookies that browsers send (these help establish full session)
        if steamCountry:
            steamCountry_cookie = create_cookie(
                name='steamCountry',
                value=steamCountry,
                domain='steamcommunity.com',
                path='/'
            )
            http_session.cookies.set_cookie(steamCountry_cookie)
        
        if webTradeEligibility:
            webTradeEligibility_cookie = create_cookie(
                name='webTradeEligibility',
                value=webTradeEligibility,
                domain='steamcommunity.com',
                path='/'
            )
            http_session.cookies.set_cookie(webTradeEligibility_cookie)
        
        # Verify cookies were set
        cookies_set = list(http_session.cookies.keys())
        print(f"   [DEBUG] Cookies set in session: {cookies_set}")
        if 'sessionid' not in cookies_set:
            results['error'] = 'sessionid cookie was not set correctly'
            results['message'] = '[FAIL] Invalid: Failed to set sessionid cookie'
            return results
        if 'steamLoginSecure' not in cookies_set:
            results['error'] = 'steamLoginSecure cookie was not set correctly'
            results['message'] = '[FAIL] Invalid: Failed to set steamLoginSecure cookie'
            return results
        
        results['tests']['session'] = True
        print("   [OK] Session created and cookies set")
    except Exception as e:
        results['error'] = f'Failed to create session: {str(e)}'
        results['message'] = '[FAIL] Invalid: Failed to setup session'
        return results
    
    # Test 3: Visit Steam community homepage first to establish full session
    # This mimics what happens when you're already logged into Steam in your browser
    print("\n[TEST] Establishing Steam session...")
    try:
        # First, visit the Steam community homepage to establish full session
        # This is what happens when you're already logged into Steam in your browser
        homepage_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        }
        
        homepage_response = http_session.get('https://steamcommunity.com/', headers=homepage_headers, timeout=10)
        print(f"   [DEBUG] Homepage response: {homepage_response.status_code}")
        
        # Small delay
        import time
        time.sleep(0.5)
    except Exception as e:
        print(f"   [WARN] Failed to visit homepage: {e}")
    
    # Test 4: Visit market listing page to get Akamai cookies
    print("\n[TEST] Testing market listing page access...")
    try:
        # Use a common CS2 item that should have price history
        test_item = 'Danger Zone Case'
        listing_url = f'https://steamcommunity.com/market/listings/730/{quote(test_item)}'
        
        listing_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Referer': 'https://steamcommunity.com/',  # Add referer from homepage
        }
        
        listing_response = http_session.get(listing_url, headers=listing_headers, timeout=10)
        
        if listing_response.status_code == 200:
            # Check for Akamai cookies
            cookies_received = list(http_session.cookies.keys())
            if 'ak_bmsc' in cookies_received:
                print("   [OK] Successfully accessed market listing page")
                print("   [OK] Received Akamai bot management cookie (ak_bmsc)")
                results['tests']['listing_page'] = True
            else:
                print("   [WARN] Accessed listing page but no ak_bmsc cookie received")
                results['tests']['listing_page'] = True  # Still valid, just no ak_bmsc
        elif listing_response.status_code == 403:
            results['error'] = 'Access forbidden (403) - cookies may be invalid or account restricted'
            results['message'] = '[FAIL] Invalid: Access forbidden (403)'
            return results
        elif listing_response.status_code == 401:
            results['error'] = 'Unauthorized (401) - cookies are invalid or expired'
            results['message'] = '[FAIL] Invalid: Unauthorized (401)'
            return results
        else:
            print(f"   [WARN] Listing page returned status {listing_response.status_code}")
            results['tests']['listing_page'] = True  # Continue test anyway
    except requests.exceptions.Timeout:
        results['error'] = 'Request timeout - Steam may be unavailable'
        results['message'] = '[FAIL] Invalid: Request timeout'
        return results
    except Exception as e:
        results['error'] = f'Error accessing listing page: {str(e)}'
        results['message'] = '[FAIL] Invalid: Failed to access listing page'
        return results
    
    # Test 5: Attempt to fetch price history (the real test)
    print("\n[TEST] Testing price history access...")
    try:
        price_history_url = "https://steamcommunity.com/market/pricehistory/"
        params = {
            'appid': '730',  # CS2
            'market_hash_name': test_item,
            'currency': 1  # USD
        }
        
        api_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Referer': listing_url,  # Add Referer header - browser sends this when navigating from listing page
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',  # Same origin since we're navigating from listing page
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Debug: Show what cookies we're sending
        cookies_before = list(http_session.cookies.keys())
        print(f"   [DEBUG] Cookies in session before request: {cookies_before}")
        
        # CRITICAL: Re-add steamLoginSecure if it's missing (Steam might clear it)
        if 'steamLoginSecure' not in cookies_before:
            print(f"   [WARN] steamLoginSecure missing! Re-adding it...")
            from requests.cookies import create_cookie
            steamLoginSecure_cookie = create_cookie(
                name='steamLoginSecure',
                value=steamLoginSecure,
                domain='steamcommunity.com',
                path='/'
            )
            http_session.cookies.set_cookie(steamLoginSecure_cookie)
            print(f"   [DEBUG] Cookies after re-adding: {list(http_session.cookies.keys())}")
        
        print(f"   [DEBUG] Request URL: {price_history_url}")
        print(f"   [DEBUG] Request params: {params}")
        
        # Small delay like a browser
        import time
        time.sleep(0.3)
        
        # Debug: Show final cookies in session
        final_cookies = list(http_session.cookies.keys())
        print(f"   [DEBUG] Final cookies in session: {final_cookies}")
        print(f"   [DEBUG] steamLoginSecure in session: {'steamLoginSecure' in final_cookies}")
        
        # Don't pass cookies explicitly - let the session handle them
        # When you access the URL directly in browser, cookies are sent automatically
        # The session should do the same - this matches browser behavior
        response = http_session.get(price_history_url, params=params, headers=api_headers, timeout=10)
        
        # Debug: Show response details and request details
        print(f"   [DEBUG] Response status: {response.status_code}")
        print(f"   [DEBUG] Response headers: {dict(response.headers)}")
        print(f"   [DEBUG] Response text (first 200 chars): {response.text[:200]}")
        
        # Debug: Check what cookies were actually sent in the request
        if hasattr(response, 'request') and hasattr(response.request, 'headers'):
            request_headers = dict(response.request.headers)
            if 'Cookie' in request_headers:
                cookie_header = request_headers['Cookie']
                print(f"   [DEBUG] Cookie header sent: {cookie_header[:200]}...")
                # Check if steamLoginSecure is in the cookie header
                if 'steamLoginSecure' in cookie_header:
                    print(f"   [OK] steamLoginSecure is in Cookie header")
                else:
                    print(f"   [ERROR] steamLoginSecure is NOT in Cookie header!")
            else:
                print(f"   [WARN] No Cookie header found in request")
        
        if response.status_code == 200:
            try:
                data = response.json()
                if 'prices' in data and len(data['prices']) > 0:
                    price_count = len(data['prices'])
                    print(f"   [OK] Successfully fetched price history!")
                    print(f"   [OK] Retrieved {price_count} price data points")
                    results['tests']['price_history'] = True
                    results['valid'] = True
                    results['message'] = f'[PASS] Valid: Cookies are working! Retrieved {price_count} price history entries.'
                    return results
                elif 'prices' in data and len(data['prices']) == 0:
                    results['error'] = 'Price history request succeeded but returned empty data. This may indicate account restrictions (e.g., no purchase in last year).'
                    results['message'] = '[WARN] Partial: Request succeeded but no price data available (account restrictions?)'
                    results['tests']['price_history'] = False
                    return results
                else:
                    results['error'] = f'Unexpected response format: {list(data.keys())}'
                    results['message'] = '[WARN] Partial: Unexpected response format'
                    results['tests']['price_history'] = False
                    return results
            except json.JSONDecodeError:
                results['error'] = 'Response is not valid JSON - may be HTML error page'
                results['message'] = '[FAIL] Invalid: Response is not JSON'
                return results
        elif response.status_code == 400:
            response_text = response.text.strip()
            if response_text == '[]':
                results['error'] = 'Steam returned 400 with empty array - no price history available or account restrictions'
                results['message'] = '[WARN] Partial: Account may not meet requirements for price history access'
                results['tests']['price_history'] = False
                return results
            else:
                results['error'] = f'Steam returned 400: {response_text[:200]}'
                results['message'] = '[FAIL] Invalid: Steam returned 400 error'
                return results
        elif response.status_code == 403:
            results['error'] = 'Access forbidden (403) - cookies may be invalid or account restricted'
            results['message'] = '[FAIL] Invalid: Access forbidden (403)'
            return results
        elif response.status_code == 401:
            results['error'] = 'Unauthorized (401) - cookies are invalid or expired'
            results['message'] = '[FAIL] Invalid: Unauthorized (401)'
            return results
        elif response.status_code == 429:
            results['error'] = 'Rate limited (429) - too many requests. Wait a moment and try again.'
            results['message'] = '[WARN] Rate Limited: Too many requests, try again later'
            return results
        else:
            results['error'] = f'Unexpected status code: {response.status_code}'
            results['message'] = f'[FAIL] Invalid: Unexpected status code {response.status_code}'
            return results
            
    except requests.exceptions.Timeout:
        results['error'] = 'Request timeout - Steam may be unavailable'
        results['message'] = '[FAIL] Invalid: Request timeout'
        return results
    except Exception as e:
        results['error'] = f'Error fetching price history: {str(e)}'
        results['message'] = '[FAIL] Invalid: Failed to fetch price history'
        return results


def update_config_file(cookies, config_path=None):
    """
    Update app/config.py with new cookies.
    
    Args:
        cookies: Dictionary of cookie name -> value pairs
        config_path: Optional path to config.py (defaults to app/config.py)
    
    Returns:
        bool: True if successful, False otherwise
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'config.py')
    
    if not os.path.exists(config_path):
        print(f"[ERROR] Config file not found: {config_path}")
        return False
    
    # Extract required cookies
    sessionid = cookies.get('sessionid', '')
    steamLoginSecure = cookies.get('steamLoginSecure', '')
    
    if not sessionid or not steamLoginSecure:
        print("[ERROR] Missing required cookies: sessionid and steamLoginSecure are required")
        return False
    
    try:
        # Read current config
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Build new DEFAULT_STEAM_COOKIES dictionary
        cookie_dict_lines = [
            "    'sessionid': '{}',".format(sessionid),
            "    'steamLoginSecure': '{}',".format(steamLoginSecure),
        ]
        
        # Add optional cookies
        if cookies.get('browserid'):
            cookie_dict_lines.append("    'browserid': '{}',".format(cookies['browserid']))
        if cookies.get('steamCountry'):
            cookie_dict_lines.append("    'steamCountry': '{}',".format(cookies['steamCountry']))
        if cookies.get('webTradeEligibility'):
            cookie_dict_lines.append("    'webTradeEligibility': '{}',".format(cookies['webTradeEligibility']))
        
        # Find and replace DEFAULT_STEAM_COOKIES
        pattern = r"DEFAULT_STEAM_COOKIES\s*=\s*\{[^}]*\}"
        replacement = "DEFAULT_STEAM_COOKIES = {{\n{}\n}}".format('\n'.join(cookie_dict_lines))
        
        new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        
        if new_content == content:
            print("[WARN] Could not find DEFAULT_STEAM_COOKIES in config file. Creating backup and updating...")
            # Create backup
            backup_path = config_path + '.backup'
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[INFO] Created backup: {backup_path}")
            
            # Try to insert after DEFAULT_STEAMAPIS_KEY
            insert_pattern = r"(DEFAULT_STEAMAPIS_KEY\s*=\s*\"[^\"]+\")\s*\n"
            insert_replacement = r"\1\n\n# Hardcoded test cookies - Updated via test_cookies.py\nDEFAULT_STEAM_COOKIES = {{\n{}\n}}\n".format('\n'.join(cookie_dict_lines))
            new_content = re.sub(insert_pattern, insert_replacement, content)
        
        # Write updated config
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"[SUCCESS] Updated {config_path} with validated cookies")
        print(f"  - sessionid: {sessionid[:20]}...")
        print(f"  - steamLoginSecure: {steamLoginSecure[:30]}...")
        if cookies.get('browserid'):
            print(f"  - browserid: {cookies['browserid']}")
        if cookies.get('steamCountry'):
            print(f"  - steamCountry: {cookies['steamCountry'][:30]}...")
        if cookies.get('webTradeEligibility'):
            print(f"  - webTradeEligibility: {cookies['webTradeEligibility'][:30]}...")
        
        return True
    except Exception as e:
        print(f"[ERROR] Failed to update config file: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return False


def main():
    """Main function to run cookie tests"""
    parser = argparse.ArgumentParser(
        description='Test Steam cookies for validity and freshness',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with environment variables:
  export STEAM_SESSIONID=your_sessionid
  export STEAM_LOGIN_SECURE=your_steam_login_secure
  python scripts/test_cookies.py
  
  # Test with command line arguments:
  python scripts/test_cookies.py --sessionid abc123 --steam-login-secure 7656119...
  
  # Test with optional browserid:
  python scripts/test_cookies.py --sessionid abc123 --steam-login-secure 7656119... --browserid 123456
        """
    )
    
    parser.add_argument('--sessionid', 
                       help='Steam session ID cookie',
                       default=os.getenv('STEAM_SESSIONID', ''))
    parser.add_argument('--steam-login-secure',
                       help='Steam login secure cookie',
                       default=os.getenv('STEAM_LOGIN_SECURE', ''))
    parser.add_argument('--browserid',
                       help='Optional browser ID cookie',
                       default=os.getenv('STEAM_BROWSERID', ''))
    parser.add_argument('--cookie-string',
                       help='Full cookie string from browser (will parse and use all cookies)',
                       default=os.getenv('STEAM_COOKIE_STRING', ''))
    parser.add_argument('--use-config',
                       action='store_true',
                       help='Use cookies from app/config.py DEFAULT_STEAM_COOKIES')
    parser.add_argument('--auto-update-config',
                       action='store_true',
                       help='Automatically update app/config.py if all tests pass (no confirmation prompt)')
    parser.add_argument('--update-config',
                       action='store_true',
                       help='Update app/config.py if all tests pass (with confirmation prompt)')
    
    args = parser.parse_args()
    
    # If --use-config flag, try to load from config
    if args.use_config:
        try:
            from app.config import DEFAULT_STEAM_COOKIES
            if not args.sessionid:
                args.sessionid = DEFAULT_STEAM_COOKIES.get('sessionid', '')
            if not args.steam_login_secure:
                args.steam_login_secure = DEFAULT_STEAM_COOKIES.get('steamLoginSecure', '')
            if not args.browserid:
                args.browserid = DEFAULT_STEAM_COOKIES.get('browserid', '')
            print("[INFO] Loaded cookies from app/config.py")
        except ImportError:
            print("[WARN] Could not import app.config, using provided cookies or environment variables")
    
    # Print header
    print("=" * 70)
    print("Steam Cookie Validation Test")
    print("=" * 70)
    print()
    
    # Check if cookies were provided
    # Either individual cookies OR cookie string must be provided
    if args.cookie_string:
        # If cookie string is provided, parse it to check if it has required cookies
        parsed = parse_cookie_string(args.cookie_string)
        if not parsed.get('sessionid') or not parsed.get('steamLoginSecure'):
            print("[ERROR] Cookie string is missing required cookies (sessionid or steamLoginSecure)")
            sys.exit(1)
    elif not args.sessionid or not args.steam_login_secure:
        print("[ERROR] Missing required cookies")
        print()
        print("Please provide cookies using one of these methods:")
        print("  1. Cookie string from browser (recommended):")
        print("     python scripts/test_cookies.py --cookie-string \"sessionid=...; steamLoginSecure=...; ...\"")
        print()
        print("  2. Environment variables:")
        print("     export STEAM_SESSIONID=your_sessionid")
        print("     export STEAM_LOGIN_SECURE=your_steam_login_secure")
        print("     python scripts/test_cookies.py")
        print()
        print("  3. Command line arguments:")
        print("     python scripts/test_cookies.py --sessionid YOUR_SESSIONID --steam-login-secure YOUR_LOGIN_SECURE")
        print()
        print("  4. Use cookies from app/config.py:")
        print("     python scripts/test_cookies.py --use-config")
        print()
        print("  5. Edit app/config.py and set DEFAULT_STEAM_COOKIES")
        print()
        sys.exit(1)
    
    # Run tests
    results = test_cookies(
        sessionid=args.sessionid,
        steamLoginSecure=args.steam_login_secure,
        browserid=args.browserid if args.browserid else None,
        cookie_string=args.cookie_string if args.cookie_string else None
    )
    
    # Extract cookies from test results for potential config update
    cookies_to_update = results.get('cookies', {})
    
    # Print results
    print()
    print("=" * 70)
    print("Test Results")
    print("=" * 70)
    print()
    print(f"Status: {results['message']}")
    print()
    
    if results.get('error'):
        print(f"Error Details: {results['error']}")
        print()
    
    print("Test Summary:")
    for test_name, passed in results.get('tests', {}).items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {test_name.replace('_', ' ').title()}: {status}")
    print()
    
    if results['valid']:
        print("[SUCCESS] Your cookies are valid and working!")
        print("   You can use these cookies in the collector and web app.")
        
        # Offer to update config.py if tests passed
        should_update = False
        if args.auto_update_config:
            should_update = True
            print()
            print("[INFO] Auto-update enabled: Updating app/config.py...")
        elif args.update_config:
            print()
            response = input("Update app/config.py with these validated cookies? (y/n): ").strip().lower()
            should_update = (response == 'y' or response == 'yes')
        
        if should_update:
            print()
            print("=" * 70)
            print("Updating app/config.py")
            print("=" * 70)
            print()
            
            # Use cookies from test results (includes all cookies that were tested)
            success = update_config_file(cookies_to_update)
            if success:
                print()
                print("[SUCCESS] Config file updated! The collector and Flask app will now use these cookies.")
            else:
                print()
                print("[WARN] Failed to update config file. You can manually update app/config.py or use:")
                print("   python scripts/import_cookies.py --cookie-string \"...\"")
        
        sys.exit(0)
    else:
        print("[FAIL] Your cookies are invalid or expired.")
        print("   Please update your cookies in the Settings page or app/config.py")
        print()
        print("To get new cookies:")
        print("  1. Log into Steam in your browser")
        print("  2. Open browser developer tools (F12)")
        print("  3. Go to Application/Storage > Cookies > https://steamcommunity.com")
        print("  4. Copy the values for 'sessionid' and 'steamLoginSecure'")
        print()
        print("Or get the full cookie string from Network tab:")
        print("  1. Go to https://steamcommunity.com/market/pricehistory/?appid=730&market_hash_name=Danger%20Zone%20Case&currency=1")
        print("  2. Open DevTools (F12) → Network tab")
        print("  3. Find the request → Headers → Request Headers → Copy Cookie header")
        sys.exit(1)


if __name__ == '__main__':
    main()
