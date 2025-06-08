from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime, timedelta
import re
from flask_session import Session  # <-- Add this import
import threading

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Needed for session

# Configure server-side session
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
Session(app)

# Game IDs and Names
GAMES = {
    '216150': 'MapleStory',
    '730': 'Counter-Strike 2'
}

# Default game ID
DEFAULT_GAME_ID = '216150'  # MapleStory

# MapleStory App ID
MAPLESTORY_APP_ID = "216150"

STEAMAPIS_KEY = "Oc7jRGOkx33t-hO_d9w_1ghv2io"  # <-- Replace with your actual SteamApis.com API key

# In-memory rate limiting
rate_limit = {
    'minute': {'count': 0, 'timestamp': 0},
    'day': {'count': 0, 'date': ''}
}
rate_limit_lock = threading.Lock()

STEAM_COOKIES = {
    'sessionid': 'acc776ba86880c3cca3d9697',
    'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAwRF8yNjY4RkI0RV8xOEEzMyIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NDkzMjIyMjUsICJuYmYiOiAxNzQwNTk0MTU0LCAiaWF0IjogMTc0OTIzNDE1NCwgImp0aSI6ICIwMDBCXzI2NkM1M0FEX0FGMjc0IiwgIm9hdCI6IDE3NDkyMzQxNTQsICJydF9leHAiOiAxNzUxODQ5MjcwLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiMTA4LjM1LjIwMS4yMjgiLCAiaXBfY29uZmlybWVyIjogIjEwOC4zNS4yMDEuMjI4IiB9.LHtbFvRyvYe-aDBvcn5uNWPPUzoYQiiiNc_KAgH0H4mjVO2e1eAh7uCW9BKEZnAaMA8y18aXdTm-5OPS4DuCBw'
    # Add 'steamMachineAuth' if needed
}

# In-memory rate limiting for Steam price history (personal use)
steam_rate_limit = {'minute': {'count': 0, 'timestamp': 0}}

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

@app.route('/', methods=['GET', 'POST'])
def index():    
    page = int(request.args.get('page', 1))
    per_page = 20
    sort_by = request.args.get('sort_by', 'item_name')
    sort_order = request.args.get('sort_order', 'asc')
    search_query = request.args.get('search', '')
    min_price = request.args.get('min_price', '')
    max_price = request.args.get('max_price', '')
    selected_game = request.args.get('game', DEFAULT_GAME_ID)

    filter_sell_listings = request.args.get('filter_sell_listings', 'off') == 'on'
    filter_sell_price = request.args.get('filter_sell_price', 'off') == 'on'
    filter_sold_7_days = request.args.get('filter_sold_7_days', 'off') == 'on'

    headers = {'User-Agent': 'Mozilla/5.0'}

    # Calculate the start index based on the page number
    api_start = (page - 1) * per_page

    # Fetch items for the current page
    params = {
        'query': search_query,
        'appid': selected_game,
        'norender': 1,
        'count': per_page,
        'start': api_start
    }
    response = make_request("https://steamcommunity.com/market/search/render/", headers, params)
    if not response or response.status_code != 200:
        return render_template('index.html', 
                             error=f"Failed to fetch data. Status code: {response.status_code if response else 'No response'}",
                             games=GAMES,
                             selected_game=selected_game)

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
        has_more=has_more,
        games=GAMES,
        selected_game=selected_game
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

        # Create a minimal version of the item data, now including image_url and game_id
        minimal_item = {
            'name': item_data['item_name'],
            'price': item_data['price_value'],
            'hash': item_data['market_hash_name'],
            'image_url': item_data.get('image_url', ''),
            'game_id': item_data.get('game_id', DEFAULT_GAME_ID)  # Add game_id
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
                             games=GAMES)
    except Exception as e:
        print(f"Error in view_cart: {str(e)}")
        return render_template('cart.html', 
                             error=str(e),
                             cart_items=[],
                             total_price=0,
                             games=GAMES)

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
    if not appid or not market_hash_name:
        return jsonify({'error': 'Missing appid or market_hash_name'}), 400

    # Validate appid
    if appid not in GAMES:
        return jsonify({'error': f'Invalid appid: {appid}'}), 400

    # Personal rate limiting
    if not check_steam_rate_limit():
        return jsonify({'error': 'Rate limit exceeded: 20 requests per minute (personal use)'}), 429

    url = "https://steamcommunity.com/market/pricehistory/"
    params = {
        'appid': appid,
        'market_hash_name': market_hash_name,
        'currency': 1  # USD
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, params=params, headers=headers, cookies=STEAM_COOKIES)
        print("Steam response status:", response.status_code)
        print("Steam response text:", response.text[:500])
        if response.status_code == 200:
            return jsonify(response.json())
        elif response.status_code == 400 and response.text.strip() == '[]':
            return jsonify({'success': True, 'prices': []})
        else:
            return jsonify({'error': f'Failed to fetch price history. Status code: {response.status_code}', 'steam_response': response.text}), 500
    except Exception as e:
        print("Exception in price_history:", str(e))
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 