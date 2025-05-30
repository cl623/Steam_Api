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

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for session

# Configure server-side session
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
Session(app)

# MapleStory App ID
MAPLESTORY_APP_ID = "216150"

STEAMAPIS_KEY = "Oc7jRGOkx33t-hO_d9w_1ghv2io"  # <-- Replace with your actual SteamApis.com API key
STEAM_LOGIN_SECURE = "76561198098290013||eyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwNF8yNjVGRTE0RF9GOUMxMyIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NDg2MjMyOTQsICJuYmYiOiAxNzM5ODk1NTIyLCAiaWF0IjogMTc0ODUzNTUyMiwgImp0aSI6ICIwMDBCXzI2NUZFMTQzX0QzMTdBIiwgIm9hdCI6IDE3NDg1MzU1MjIsICJydF9leHAiOiAxNzUxMTM4MTYxLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiNzEuMTcyLjQ2LjE2IiwgImlwX2NvbmZpcm1lciI6ICI3MS4xNzIuNDYuMTYiIH0.jrX81LRURwO6djTZZxKTyYEnyYQBe98DAf5wNO6BpL9vihwTcwJG_2LVBAcP8E4ZBIu43ABW7VxlmKais_XKAg"
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

@app.route('/', methods=['GET', 'POST'])
def index():    
    page = int(request.args.get('page', 1))
    per_page = 20
    sort_by = request.args.get('sort_by', 'item_name')
    sort_order = request.args.get('sort_order', 'asc')
    search_query = request.args.get('search', '')
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')

    filter_sell_listings = request.args.get('filter_sell_listings', 'off') == 'on'
    filter_sell_price = request.args.get('filter_sell_price', 'off') == 'on'
    filter_sold_7_days = request.args.get('filter_sold_7_days', 'off') == 'on'

    headers = {'User-Agent': 'Mozilla/5.0'}

    # Calculate the start index based on the page number
    api_start = (page - 1) * per_page

    # Fetch items for the current page
    params = {
        'query': search_query,
        'appid': '216150',
        'norender': 1,
        'count': per_page,
        'start': api_start
    }
    response = make_request("https://steamcommunity.com/market/search/render/", headers, params)
    if not response or response.status_code != 200:
        return render_template('index.html', error=f"Failed to fetch data. Status code: {response.status_code if response else 'No response'}")

    data = response.json()
    results = data.get('results', [])
    items = []
    
    for result in results:
        sell_listings = int(result.get('sell_listings', 0))
        price_text = result.get('sell_price_text', '').replace(',', '').strip()
        price_match = re.search(r'(\d+(\.\d+)?)', price_text)
        price_value = float(price_match.group(1)) if price_match else 0.0

        image_url = None
        if 'asset_description' in result and 'icon_url' in result['asset_description']:
            image_url = "https://steamcommunity-a.akamaihd.net/economy/image/" + result['asset_description']['icon_url']

        items.append({
            'item_name': result.get('name'),
            'price': result.get('sell_price_text'),
            'price_value': price_value,
            'quantity': sell_listings,
            'image_url': image_url,
            'market_hash_name': result.get('hash_name', ''),
            'market_id': result.get('id', '')
        })

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

    # Sorting logic
    reverse = (sort_order == 'desc')
    if sort_by in ['item_name', 'price', 'quantity']:
        filtered_items.sort(key=lambda x: x[sort_by] if sort_by != 'price' else x['price_value'], reverse=reverse)

    # Check if there are more results available
    has_more = len(results) == per_page

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

        # Create a minimal version of the item data, now including image_url
        minimal_item = {
            'name': item_data['item_name'],
            'price': item_data['price_value'],
            'hash': item_data['market_hash_name'],
            'image_url': item_data.get('image_url', '')
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
def price_history():
    appid = request.args.get('appid')
    market_hash_name = request.args.get('market_hash_name')
    clear_cache = request.args.get('clear_cache', '0') == '1'
    
    # Debug logging
    print("Price History Request:")
    print(f"AppID: {appid}")
    print(f"Market Hash Name: {market_hash_name}")
    
    if not appid or not market_hash_name:
        return jsonify({'error': 'Missing appid or market_hash_name'}), 400

    # Optionally clear cache for this item
    cache_key = f"{appid}_{market_hash_name}"
    if clear_cache and cache_key in PRICE_HISTORY_CACHE:
        del PRICE_HISTORY_CACHE[cache_key]
        print(f"Cache cleared for {cache_key}")

    # Check cache first
    cached_data = get_cached_price_history(appid, market_hash_name)
    if cached_data:
        print("Returning cached price history data")
        return jsonify(cached_data)

    # Personal rate limiting
    if not check_steam_rate_limit():
        return jsonify({'error': 'Rate limit exceeded: 20 requests per minute (personal use)'}), 429

    url = "https://steamcommunity.com/market/pricehistory/"
    encoded_hash_name = urllib.parse.quote(market_hash_name, safe='')
    params = {
        'appid': appid,
        'market_hash_name': market_hash_name,  # requests will encode, but let's log both
        'currency': 1  # USD
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': f'https://steamcommunity.com/market/listings/{appid}/{encoded_hash_name}'
    }
    
    try:
        print("Making request to Steam with params:", params)
        print("Encoded market_hash_name:", encoded_hash_name)
        print("Using headers:", headers)
        print("Using cookies:", STEAM_COOKIES)
        
        time.sleep(1)  # 1 second delay between requests
        response = requests.get(url, params=params, headers=headers, cookies=STEAM_COOKIES)
        print("Steam response status:", response.status_code)
        print("Steam response headers:", dict(response.headers))
        print("Steam response text:", response.text[:1000])
        
        if response.status_code == 200:
            data = response.json()
            set_cached_price_history(appid, market_hash_name, data)
            return jsonify(data)
        elif response.status_code == 400 and response.text.strip() == '[]':
            empty_data = {'success': True, 'prices': []}
            set_cached_price_history(appid, market_hash_name, empty_data)
            return jsonify(empty_data)
        elif response.status_code == 429:
            if cached_data:
                print("Rate limited, returning expired cache")
                return jsonify(cached_data)
            return jsonify({
                'error': 'Steam rate limit exceeded. Please try again in a few minutes.',
                'request_params': params
            }), 429
        else:
            return jsonify({
                'error': f'Failed to fetch price history. Status code: {response.status_code}',
                'steam_response': response.text,
                'request_params': params
            }), 500
    except Exception as e:
        print("Exception in price_history:", str(e))
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 