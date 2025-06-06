from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime, timedelta
import re
from flask_session import Session  # <-- Add this import
import threading
from functools import lru_cache
import urllib.parse
from market_data_collector import MarketDataCollector  # Add this import
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for session

# Configure server-side session
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
Session(app)

# MapleStory App ID
MAPLESTORY_APP_ID = "216150"

STEAMAPIS_KEY = "Oc7jRGOkx33t-hO_d9w_1ghv2io"  # <-- Replace with your actual SteamApis.com API key
STEAM_LOGIN_SECURE = "76561198098290013||eyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwNF8yNjVGRTE0RF9GOUMxMyIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NDkyMTk0MzUsICJuYmYiOiAxNzQwNDkyMjEyLCAiaWF0IjogMTc0OTEzMjIxMiwgImp0aSI6ICIwMDBCXzI2NjhGQjM1XzYwMzdEIiwgIm9hdCI6IDE3NDg1MzU1MjIsICJydF9leHAiOiAxNzUxMTM4MTYxLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiNzEuMTcyLjQ2LjE2IiwgImlwX2NvbmZpcm1lciI6ICI3MS4xNzIuNDYuMTYiIH0.fMLDLDJtCmLofetkf5yq5Dtb32vet-CteSlGShYsgz0L6DDm29gfvpeP54sXAc2e5vHGu1a4LpFt4rbWJi5KCA"
STEAM_SESSION_ID = "e81e5ffc77a8f27479115336"
# In-memory rate limiting
rate_limit = {
    'minute': {'count': 0, 'timestamp': 0},
    'day': {'count': 0, 'date': ''}
}
rate_limit_lock = threading.Lock()

STEAM_COOKIES = {
    'sessionid': STEAM_SESSION_ID,
    'steamLoginSecure': STEAM_LOGIN_SECURE
    # Add 'steamMachineAuth' if needed
}

# In-memory rate limiting for Steam price history (personal use)
steam_rate_limit = {'minute': {'count': 0, 'timestamp': 0}}

# Add after other global variables
PRICE_HISTORY_CACHE = {}
PRICE_HISTORY_CACHE_DURATION = 300  # 5 minutes in seconds

# Database configuration
DB_PATH = 'market_data.db'  # Use the same database path as MarketDataCollector

# Initialize market data collector with the same database path
market_collector = MarketDataCollector(db_path=DB_PATH)

# Ensure database exists and has required tables
def initialize_database():
    """Initialize the database if it doesn't exist."""
    if not os.path.exists(DB_PATH):
        market_collector.initialize_database()
        print(f"Initialized database at {DB_PATH}")

# Call initialize_database when the app starts
initialize_database()

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
    now = time.time()
    if now - steam_rate_limit['minute']['timestamp'] > 60:
        steam_rate_limit['minute']['count'] = 0
        steam_rate_limit['minute']['timestamp'] = now
    if steam_rate_limit['minute']['count'] >= 20:
        return False
    steam_rate_limit['minute']['count'] += 1
    return True

def get_cached_price_history(appid, market_hash_name):
    cache_key = f"{appid}_{market_hash_name}"
    if cache_key in PRICE_HISTORY_CACHE:
        cache_time, cache_data = PRICE_HISTORY_CACHE[cache_key]
        if time.time() - cache_time < PRICE_HISTORY_CACHE_DURATION:
            return cache_data
    return None

def set_cached_price_history(appid, market_hash_name, data):
    cache_key = f"{appid}_{market_hash_name}"
    PRICE_HISTORY_CACHE[cache_key] = (time.time(), data)

@app.route('/')
def index():
    page = int(request.args.get('page', 1))
    per_page = 20
    sort_by = request.args.get('sort_by', 'item_name')
    sort_order = request.args.get('sort_order', 'asc')
    search_query = request.args.get('search', '')
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')
    game_id = request.args.get('game', 'csgo')  # Default to CS:GO

    # Set the current game
    market_collector.set_game(game_id)
    current_game_config = market_collector.get_current_game()
    print(f"\n=== Starting new request ===")
    print(f"Game ID: {game_id}")
    print(f"Current game config: {current_game_config}")

    filter_sell_listings = request.args.get('filter_sell_listings', 'off') == 'on'
    filter_sell_price = request.args.get('filter_sell_price', 'off') == 'on'
    filter_sold_7_days = request.args.get('filter_sold_7_days', 'off') == 'on'

    headers = {'User-Agent': 'Mozilla/5.0'}
    print(f"Using headers: {headers}")
    print(f"Using cookies: {STEAM_COOKIES}")

    # Calculate the start index based on the page number
    api_start = (page - 1) * per_page

    # Fetch items for the current page
    params = {
        'query': search_query,
        'appid': current_game_config['app_id'],
        'norender': 1,
        'count': per_page,
        'start': api_start
    }
    print(f"Request params: {params}")
    
    response = make_request("https://steamcommunity.com/market/search/render/", headers, params)
    print(f"Response status code: {response.status_code if response else 'No response'}")
    if response:
        print(f"Response headers: {dict(response.headers)}")
        print(f"Response text preview: {response.text[:1000] if response.text else 'No text'}")

    if not response or response.status_code != 200:
        error_msg = f"Failed to fetch data. Status code: {response.status_code if response else 'No response'}"
        print(f"Error: {error_msg}")
        return render_template('index.html', error=error_msg)

    try:
        data = response.json()
        print(f"Parsed JSON data: {data}")
        results = data.get('results', [])
        print(f"Number of results: {len(results)}")
        
        items = []
        for result in results:
            sell_listings = int(result.get('sell_listings', 0))
            price_text = result.get('sell_price_text', '').replace(',', '').strip()
            price_match = re.search(r'(\d+(\.\d+)?)', price_text)
            price_value = float(price_match.group(1)) if price_match else 0.0

            image_url = None
            if 'asset_description' in result and 'icon_url' in result['asset_description']:
                image_url = "https://steamcommunity-a.akamaihd.net/economy/image/" + result['asset_description']['icon_url']

            # Get the app ID from the asset description or use the current game's app_id
            app_id = None
            if 'asset_description' in result and 'appid' in result['asset_description']:
                app_id = str(result['asset_description']['appid'])
            if not app_id:
                app_id = current_game_config['app_id']
                print(f"Using current game app_id {app_id} for {result.get('name')}")

            item = {
                'item_name': result.get('name'),
                'price': result.get('sell_price_text'),
                'price_value': price_value,
                'quantity': sell_listings,
                'image_url': image_url,
                'market_hash_name': result.get('hash_name', ''),
                'market_id': result.get('id', ''),
                'app_id': app_id  # Add the app ID to the item data
            }
            items.append(item)
            print(f"Processed item: {item['item_name']} with app ID: {app_id}")

        # Apply filters to items
        filtered_items = []
        for item in items:
            if filter_sell_listings and item['quantity'] <= 0:
                continue
            if filter_sell_price and item['price_value'] <= 0:
                continue
            if min_price and item['price_value'] < float(min_price):
                continue
            if max_price and item['price_value'] > float(max_price):
                continue
            filtered_items.append(item)

        print(f"Number of items after filtering: {len(filtered_items)}")

        # Sorting logic
        reverse = (sort_order == 'desc')
        if sort_by in ['item_name', 'price', 'quantity']:
            filtered_items.sort(key=lambda x: x[sort_by] if sort_by != 'price' else x['price_value'], reverse=reverse)

        # Check if there are more results available
        has_more = len(results) == per_page
        print(f"Has more results: {has_more}")

        return render_template(
            'index.html',
            listings=filtered_items,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            filter_sell_listings=filter_sell_listings,
            filter_sell_price=filter_sell_price,
            filter_sold_7_days=filter_sold_7_days,
            search_query=search_query,
            min_price=min_price,
            max_price=max_price,
            has_more=has_more
        )
    except Exception as e:
        print(f"Error processing response: {str(e)}")
        return render_template('index.html', error=f"Error processing response: {str(e)}")

@app.route('/api/listings')
def get_listings():
    try:
        url = f"https://steamcommunity.com/market/listings/{MAPLESTORY_APP_ID}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            market_data = []
            market_table = soup.find('div', {'id': 'market_listing_table'})
            
            if market_table:
                listings = market_table.find_all('div', {'class': 'market_listing_row'})
                for listing in listings:
                    try:
                        item_name = listing.find('span', {'class': 'market_listing_item_name'}).text.strip()
                        price = listing.find('span', {'class': 'market_listing_price_with_fee'}).text.strip()
                        quantity = listing.find('span', {'class': 'market_listing_num_listings_qty'}).text.strip()
                        
                        market_data.append({
                            'item_name': item_name,
                            'price': price,
                            'quantity': quantity
                        })
                    except AttributeError:
                        continue
            
            return jsonify(market_data)
        else:
            return jsonify({'error': f"Failed to fetch data. Status code: {response.status_code}"}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    try:
        item_data = request.json
        if not item_data:
            return jsonify({'error': 'No item data provided'}), 400

        # Initialize cart if it doesn't exist
        if 'cart' not in session:
            session['cart'] = []
            session.modified = True

        # Convert existing cart items to a list if it's not already
        if not isinstance(session['cart'], list):
            session['cart'] = []
            session.modified = True

        # Get the app_id from the item data or use the current game's app_id
        app_id = item_data.get('app_id')
        if not app_id:
            app_id = market_collector.get_current_game()['app_id']
            print(f"Using current game app_id {app_id} for {item_data['item_name']}")

        # Create a minimal version of the item data
        minimal_item = {
            'name': item_data['item_name'],
            'price': item_data['price_value'],
            'hash': item_data['market_hash_name'],
            'image_url': item_data.get('image_url', ''),
            'app_id': app_id  # Use the determined app_id
        }

        # Check if item is already in cart using item_name
        for item in session['cart']:
            if item['name'] == minimal_item['name']:
                return jsonify({'error': 'Item already in cart'}), 400

        # Add item to cart
        session['cart'].append(minimal_item)
        session.modified = True

        # Debug information
        print(f"Current cart size: {len(session['cart'])}")
        print(f"Cart contents: {session['cart']}")

        return jsonify({
            'message': 'Item added to cart',
            'cart_count': len(session['cart']),
            'cart_items': session['cart']
        })
    except Exception as e:
        print(f"Error in add_to_cart: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    try:
        item_name = request.json.get('item_name')
        if not item_name:
            return jsonify({'error': 'No item name provided'}), 400

        if 'cart' in session:
            # Ensure cart is a list
            if not isinstance(session['cart'], list):
                session['cart'] = []
            
            session['cart'] = [item for item in session['cart'] if item['name'] != item_name]
            session.modified = True

            # Debug information
            print(f"Remove from cart - Current cart size: {len(session['cart'])}")
            print(f"Remove from cart - Cart contents: {session['cart']}")

        return jsonify({
            'message': 'Item removed from cart',
            'cart_count': len(session.get('cart', [])),
            'cart_items': session.get('cart', [])
        })
    except Exception as e:
        print(f"Error in remove_from_cart: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/cart')
def view_cart():
    try:
        # Ensure cart is a list
        cart_items = session.get('cart', [])
        if not isinstance(cart_items, list):
            cart_items = []
            session['cart'] = cart_items
            session.modified = True

        # Debug information
        print(f"View cart - Current cart size: {len(cart_items)}")
        print(f"View cart - Cart contents: {cart_items}")

        # Calculate total price
        total_price = sum(item['price'] for item in cart_items)
        
        return render_template('cart.html', 
                             cart_items=cart_items,
                             total_price=total_price,
                             MAPLESTORY_APP_ID=MAPLESTORY_APP_ID)
    except Exception as e:
        print(f"Error in view_cart: {str(e)}")
        return render_template('cart.html', 
                             error=str(e),
                             cart_items=[],
                             total_price=0,
                             MAPLESTORY_APP_ID=MAPLESTORY_APP_ID)

@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    try:
        session['cart'] = []
        session.modified = True
        
        # Debug information
        print("Cart cleared")
        print(f"Current cart size: {len(session.get('cart', []))}")

        return jsonify({
            'message': 'Cart cleared',
            'cart_count': 0,
            'cart_items': []
        })
    except Exception as e:
        print(f"Error in clear_cart: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pricehistory')
def get_price_history():
    market_hash_name = request.args.get('market_hash_name')
    app_id = request.args.get('app_id')
    
    if not market_hash_name:
        return jsonify({'error': 'Market hash name is required'}), 400
        
    try:
        # First check if we have recent data in the database
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get the item's app_id from the database if not provided
            if not app_id:
                cursor.execute('SELECT app_id FROM items WHERE market_hash_name = ?', (market_hash_name,))
                result = cursor.fetchone()
                if result and result['app_id']:
                    app_id = result['app_id']
                    print(f"Using app_id {app_id} from database for {market_hash_name}")
            
            # Use the app_id from the request or database, fallback to game config
            if not app_id:
                app_id = market_collector.get_current_game()['app_id']
                print(f"Using app_id {app_id} from game config for {market_hash_name}")
            
            # Calculate date 6 months ago
            six_months_ago = datetime.now() - timedelta(days=180)
            
            # Get price history from database
            cursor.execute('''
                SELECT ph.timestamp, ph.price, ph.volume
                FROM price_history ph
                JOIN items i ON ph.item_id = i.id
                WHERE i.market_hash_name = ? AND ph.timestamp >= ?
                ORDER BY ph.timestamp ASC
            ''', (market_hash_name, six_months_ago))
            
            db_prices = cursor.fetchall()
            
            if db_prices:
                print(f"Found {len(db_prices)} price history entries in database for {market_hash_name}")
                # Format the data to match the expected response structure
                formatted_prices = []
                for row in db_prices:
                    timestamp = row['timestamp']
                    # Handle both string and datetime timestamps
                    if isinstance(timestamp, str):
                        try:
                            timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            print(f"Warning: Could not parse timestamp {timestamp}")
                            continue
                    formatted_prices.append([
                        timestamp.strftime('%b %d %Y %H: +0'),
                        row['price'],
                        row['volume']
                    ])
                return jsonify({'prices': formatted_prices})
            
            # If no recent data in database, fetch from Steam
            print(f"No recent data in database for {market_hash_name}, fetching from Steam...")
            
            # Check cache first
            cache_key = f"{market_hash_name}_{app_id}"
            cached_data = get_cached_price_history(app_id, market_hash_name)
            if cached_data:
                # Filter cached data to last 6 months
                filtered_prices = [
                    price for price in cached_data.get('prices', [])
                    if datetime.strptime(price[0], '%b %d %Y %H: +0') >= six_months_ago
                ]
                if filtered_prices:
                    print(f"Returning {len(filtered_prices)} cached price history entries for {market_hash_name}")
                    return jsonify({'prices': filtered_prices})
            
            # Fetch from Steam API
            print(f"Fetching price history from Steam API for {market_hash_name} with app_id {app_id}")
            url = f"https://steamcommunity.com/market/pricehistory/"
            params = {
                'appid': app_id,
                'market_hash_name': market_hash_name,
                'norender': 1
            }
            
            # Use the headers defined at the top of the file
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': f'https://steamcommunity.com/market/listings/{app_id}/{urllib.parse.quote(market_hash_name)}'
            }
            
            response = requests.get(url, params=params, headers=headers, cookies=STEAM_COOKIES)
            print(f"Steam API response status: {response.status_code}")
            
            if response.status_code == 429:
                print("Rate limit exceeded, returning cached data if available")
                cached_data = get_cached_price_history(app_id, market_hash_name)
                if cached_data:
                    return jsonify(cached_data)
                return jsonify({'error': 'Rate limit exceeded'}), 429
                
            if response.status_code != 200:
                print(f"Error from Steam API: {response.status_code}")
                return jsonify({'error': 'Failed to fetch price history'}), response.status_code
                
            data = response.json()
            if not data.get('success'):
                print(f"Steam API returned error: {data.get('message', 'Unknown error')}")
                return jsonify({'error': data.get('message', 'Failed to fetch price history')}), 400
                
            # Filter to last 6 months before caching
            if 'prices' in data:
                data['prices'] = [
                    price for price in data['prices']
                    if datetime.strptime(price[0], '%b %d %Y %H: +0') >= six_months_ago
                ]
            
            # Cache the response
            set_cached_price_history(app_id, market_hash_name, data)
            
            # Store in database
            try:
                cursor.execute('SELECT id FROM items WHERE market_hash_name = ?', (market_hash_name,))
                item_result = cursor.fetchone()
                if item_result:
                    item_id = item_result['id']
                    for price in data.get('prices', []):
                        timestamp = datetime.strptime(price[0], '%b %d %Y %H: +0')
                        cursor.execute('''
                            INSERT OR REPLACE INTO price_history (item_id, timestamp, price, volume)
                            VALUES (?, ?, ?, ?)
                        ''', (item_id, timestamp, price[1], price[2]))
                    conn.commit()
                    print(f"Stored {len(data.get('prices', []))} price history entries in database")
            except Exception as e:
                print(f"Error storing price history in database: {str(e)}")
                import traceback
                traceback.print_exc()
            
            return jsonify(data)
            
    except Exception as e:
        print(f"Error in get_price_history: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 