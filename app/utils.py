"""Utility functions for the Steam Market application"""
import requests
import time
import base64
import json
from flask import session
from app.config import DEFAULT_STEAM_COOKIES, DEFAULT_STEAMAPIS_KEY

# In-memory rate limiting for Steam price history (personal use)
steam_rate_limit = {'minute': {'count': 0, 'timestamp': 0}}

def parse_cookie_string(cookie_string):
    """
    Parse a cookie string from browser's Cookie header into a dictionary.
    
    Args:
        cookie_string: Full cookie string from browser (e.g., "sessionid=abc; steamLoginSecure=xyz")
    
    Returns:
        dict: Dictionary of cookie name -> value pairs
    """
    cookies = {}
    if not cookie_string:
        return cookies
    for cookie_pair in cookie_string.split('; '):
        if '=' in cookie_pair:
            name, value = cookie_pair.split('=', 1)
            cookies[name.strip()] = value.strip()
    return cookies

def validate_steam_token_audience(steamLoginSecure):
    """
    Validate that the steamLoginSecure token has the correct audience for Steam Community.
    
    Returns:
        tuple: (is_valid, audience_list, error_message)
    """
    try:
        # steamLoginSecure format: "STEAM_ID%7C%7CJWT_TOKEN"
        # The JWT token is URL-encoded, so we need to decode it first
        if '%7C%7C' in steamLoginSecure:
            parts = steamLoginSecure.split('%7C%7C', 1)
            if len(parts) != 2:
                print(f"[VALIDATION] Invalid format: no %7C%7C separator found")
                return False, [], "Invalid steamLoginSecure format"
            jwt_token = parts[1]
        elif '||' in steamLoginSecure:
            parts = steamLoginSecure.split('||', 1)
            if len(parts) != 2:
                print(f"[VALIDATION] Invalid format: no || separator found")
                return False, [], "Invalid steamLoginSecure format"
            jwt_token = parts[1]
        else:
            # Assume it's just the JWT token
            jwt_token = steamLoginSecure
        
        # JWT format: header.payload.signature
        # We only need the payload (middle part)
        jwt_parts = jwt_token.split('.')
        if len(jwt_parts) != 3:
            print(f"[VALIDATION] Invalid JWT format: expected 3 parts, got {len(jwt_parts)}")
            return False, [], "Invalid JWT format"
        
        # Decode the payload (base64url)
        payload = jwt_parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        # Decode base64
        decoded = base64.urlsafe_b64decode(payload)
        token_data = json.loads(decoded)
        
        # Check audience
        audience = token_data.get('aud', [])
        if isinstance(audience, str):
            audience = [audience]
        
        print(f"[VALIDATION] Decoded token audience: {audience}")
        
        # Check if 'web:community' is in the audience
        has_community = 'web:community' in audience
        
        if not has_community:
            error_msg = (
                f"Token audience is {audience}, but needs 'web:community'. "
                f"This token is for {audience[0] if audience else 'unknown'} access. "
                f"Please get fresh cookies from https://steamcommunity.com (not store.steampowered.com)."
            )
            print(f"[VALIDATION] {error_msg}")
            return False, audience, error_msg
        
        print(f"[VALIDATION] Token has correct audience: {audience}")
        return True, audience, None
        
    except Exception as e:
        import traceback
        print(f"[VALIDATION] Exception during validation: {str(e)}")
        print(f"[VALIDATION] Traceback: {traceback.format_exc()}")
        return False, [], f"Error validating token: {str(e)}"

def get_steam_cookies():
    """Get Steam cookies from session or return defaults"""
    # Check if user has cookies in session (from Settings page)
    if 'steam_cookies' in session and session['steam_cookies']:
        cookies = session['steam_cookies']
        # Validate that cookies have required fields
        if cookies.get('sessionid') and cookies.get('steamLoginSecure'):
            sessionid_preview = cookies.get('sessionid', '')[:20]
            print(f"Using cookies from session (Settings) - sessionid: {sessionid_preview}...")
            
            # Validate token audience
            steamLoginSecure = cookies.get('steamLoginSecure', '')
            is_valid, audience, error_msg = validate_steam_token_audience(steamLoginSecure)
            if not is_valid:
                print(f"WARNING: {error_msg}")
                print(f"Token audience: {audience}")
                print("Please update your cookies from https://steamcommunity.com (not store.steampowered.com)")
            
            return cookies
    return DEFAULT_STEAM_COOKIES.copy()

def get_steamapis_key():
    """Get SteamApis key from session or return default"""
    if 'steamapis_key' in session and session['steamapis_key']:
        return session['steamapis_key']
    return DEFAULT_STEAMAPIS_KEY

def make_request(url, headers, params=None, max_retries=3):
    """Helper function to make requests with retry logic and delay"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                # If rate limited, wait longer
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            else:
                return response
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(1)
    return None

def check_steam_rate_limit():
    """Check if we can make a Steam API request (rate limiting)"""
    now = time.time()
    if now - steam_rate_limit['minute']['timestamp'] > 60:
        steam_rate_limit['minute']['count'] = 0
        steam_rate_limit['minute']['timestamp'] = now
    if steam_rate_limit['minute']['count'] >= 20:
        return False
    steam_rate_limit['minute']['count'] += 1
    return True

def get_price_history_from_db(market_hash_name, game_id, days=90, db_path=None):
    """Get price history from database for faster loading"""
    try:
        import sqlite3
        from datetime import datetime, timedelta
        import os
        import re
        
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'market_data.db')
        
        if not os.path.exists(db_path):
            return None
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            # Get item_id
            cursor.execute('SELECT id FROM items WHERE market_hash_name = ? AND game_id = ?',
                         (market_hash_name, game_id))
            item_row = cursor.fetchone()
            if not item_row:
                return None
            
            item_id = item_row[0]
            
            # Get price history
            cursor.execute('''
                SELECT timestamp, price, volume 
                FROM price_history 
                WHERE item_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            ''', (item_id, cutoff_date.strftime('%Y-%m-%d')))
            
            entries = cursor.fetchall()
            if not entries:
                return None
            
            # Parse Steam timestamp format and filter to last N days
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            filtered_entries = []
            
            for timestamp_str, price, volume in entries:
                try:
                    # Steam format: "Dec 06 2018 01: +0"
                    clean_timestamp = re.sub(r'\s+\+\d+$', '', timestamp_str).strip()
                    parts = re.match(r'(\w+)\s+(\d+)\s+(\d+)\s+(\d+):', clean_timestamp)
                    if parts:
                        month = month_names.index(parts.group(1))
                        day = int(parts.group(2))
                        year = int(parts.group(3))
                        hour = int(parts.group(4))
                        entry_date = datetime(year, month + 1, day, hour)  # month is 0-indexed in datetime
                        
                        if entry_date >= cutoff_date:
                            # Return in Steam format: [timestamp, price, volume]
                            filtered_entries.append([timestamp_str, float(price), int(volume)])
                except (ValueError, AttributeError, IndexError) as e:
                    # Skip entries with invalid timestamps
                    continue
            
            if filtered_entries:
                return {'prices': filtered_entries, 'source': 'database'}
            return None
    except Exception as e:
        print(f"Error querying database: {e}")
        return None
