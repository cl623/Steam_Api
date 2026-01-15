"""Flask routes for the Steam Market application"""
from flask import Blueprint, render_template, jsonify, request, session, url_for
import requests
import json
import time
import re
from app.config import GAMES, DEFAULT_GAME_ID
from app.utils import (
    get_steam_cookies, get_steamapis_key, make_request, 
    check_steam_rate_limit, get_price_history_from_db, validate_steam_token_audience
)

bp = Blueprint('main', __name__)

@bp.route('/', methods=['GET', 'POST'])
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
        # Get cart items for template
        cart_items = session.get('cart', [])
        if not isinstance(cart_items, list):
            cart_items = []
        cart_item_names = {item['name'] for item in cart_items}
        return render_template('index.html', 
                             error=f"Failed to fetch data. Status code: {response.status_code if response else 'No response'}",
                             games=GAMES,
                             selected_game=selected_game,
                             cart_item_names=cart_item_names)

    data = response.json()
    results = data.get('results', [])
    items = []
    
    for result in results:
        sell_listings = int(result.get('sell_listings', 0))
        price_text = result.get('sell_price_text', '').replace(',', '').strip()
        price_match = re.search(r'(\d+(\.\d+)?)', price_text)
        price_value = float(price_match.group(1)) if price_match else 0.0

        market_hash_name = result.get('hash_name', '')
        
        # Get image URL if available
        image_url = None
        if 'asset_description' in result and 'icon_url' in result['asset_description']:
            image_url = "https://steamcommunity-a.akamaihd.net/economy/image/" + result['asset_description']['icon_url']

        items.append({
            'item_name': result.get('name'),
            'price': result.get('sell_price_text'),
            'price_value': price_value,
            'quantity': sell_listings,
            'market_hash_name': market_hash_name,
            'market_id': result.get('id', ''),
            'image_url': image_url
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

    # Get cart items to check which items are already in cart
    cart_items = session.get('cart', [])
    if not isinstance(cart_items, list):
        cart_items = []
    cart_item_names = {item['name'] for item in cart_items}
    dark_mode = session.get('dark_mode', False)
    
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
        selected_game=selected_game,
        cart_item_names=cart_item_names,
        dark_mode=dark_mode
    )

@bp.route('/add_to_cart', methods=['POST'])
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

@bp.route('/remove_from_cart', methods=['POST'])
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

        return jsonify({
            'message': 'Item removed from cart',
            'cart_count': len(session.get('cart', [])),
            'cart_items': session.get('cart', [])
        })
    except Exception as e:
        print(f"Error in remove_from_cart: {str(e)}")
        return jsonify({'error': str(e)}), 500

@bp.route('/cart')
def view_cart():
    try:
        # Ensure cart is a list
        cart_items = session.get('cart', [])
        if not isinstance(cart_items, list):
            cart_items = []
            session['cart'] = cart_items
            session.modified = True

        # Calculate total price
        total_price = sum(item['price'] for item in cart_items)
        dark_mode = session.get('dark_mode', False)
        
        return render_template('cart.html', 
                             cart_items=cart_items,
                             total_price=total_price,
                             games=GAMES,
                             dark_mode=dark_mode)
    except Exception as e:
        print(f"Error in view_cart: {str(e)}")
        return render_template('cart.html', 
                             error=str(e),
                             cart_items=[],
                             total_price=0,
                             games=GAMES)

@bp.route('/clear_cart', methods=['POST'])
def clear_cart():
    try:
        session['cart'] = []
        session.modified = True

        return jsonify({
            'message': 'Cart cleared',
            'cart_count': 0,
            'cart_items': []
        })
    except Exception as e:
        print(f"Error in clear_cart: {str(e)}")
        return jsonify({'error': str(e)}), 500

@bp.route('/api/pricehistory')
def price_history():
    appid = request.args.get('appid')
    market_hash_name = request.args.get('market_hash_name')
    if not appid or not market_hash_name:
        return jsonify({'error': 'Missing appid or market_hash_name'}), 400

    # Validate appid
    if appid not in GAMES:
        return jsonify({'error': f'Invalid appid: {appid}'}), 400

    # Try database first for faster response
    db_data = get_price_history_from_db(market_hash_name, appid, days=90)
    if db_data:
        print(f"Returning price history from database for {market_hash_name} ({len(db_data['prices'])} entries)")
        return jsonify(db_data)

    # If no database data, fall back to API
    print(f"No database data found for {market_hash_name}, fetching from API...")

    # Personal rate limiting
    if not check_steam_rate_limit():
        return jsonify({'error': 'Rate limit exceeded: 20 requests per minute (personal use)'}), 429

    url = "https://steamcommunity.com/market/pricehistory/"
    
    params = {
        'appid': appid,
        'market_hash_name': market_hash_name,
        'currency': 1  # USD
    }
    
    # Use a session to maintain cookies across requests
    # This is critical - Steam uses Akamai bot management that requires visiting the page first
    http_session = requests.Session()  # Renamed to avoid conflict with Flask session
    steam_cookies = get_steam_cookies()
    
    # Debug: Check if cookies are configured
    if not steam_cookies.get('sessionid') or not steam_cookies.get('steamLoginSecure'):
        print("Warning: Steam cookies may not be properly configured")
        return jsonify({
            'error': 'Steam cookies not configured. Please set your sessionid and steamLoginSecure in Settings.',
            'prices': []
        }), 400
    
    # Validate token audience before making request
    steamLoginSecure = steam_cookies.get('steamLoginSecure', '')
    print(f"[VALIDATION] Checking token audience for steamLoginSecure: {steamLoginSecure[:50]}...")
    is_valid, audience, error_msg = validate_steam_token_audience(steamLoginSecure)
    print(f"[VALIDATION] Result: is_valid={is_valid}, audience={audience}, error_msg={error_msg}")
    if not is_valid:
        print(f"[VALIDATION] ERROR: {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg,
            'suggestion': 'Please get fresh cookies from https://steamcommunity.com (not store.steampowered.com). The token audience must include "web:community".',
            'account_requirements': 'Steam account must have made a purchase in the last year, have Steam Guard enabled for 15 days, and have market access.'
        }), 400
    print(f"[VALIDATION] Token audience is valid: {audience}")
    
    # Set cookies properly in session with correct domain
    # This ensures cookies are sent with requests to steamcommunity.com
    from requests.cookies import create_cookie
    
    sessionid_cookie = create_cookie(
        name='sessionid',
        value=steam_cookies['sessionid'],
        domain='steamcommunity.com',
        path='/'
    )
    steamLoginSecure_cookie = create_cookie(
        name='steamLoginSecure',
        value=steam_cookies['steamLoginSecure'],
        domain='steamcommunity.com',
        path='/'
    )
    http_session.cookies.set_cookie(sessionid_cookie)
    http_session.cookies.set_cookie(steamLoginSecure_cookie)
    
    # Optional cookies that help establish full session (set if available)
    if steam_cookies.get('browserid'):
        browserid_cookie = create_cookie(
            name='browserid',
            value=steam_cookies['browserid'],
            domain='steamcommunity.com',
            path='/'
        )
        http_session.cookies.set_cookie(browserid_cookie)
    
    if steam_cookies.get('steamCountry'):
        steamCountry_cookie = create_cookie(
            name='steamCountry',
            value=steam_cookies['steamCountry'],
            domain='steamcommunity.com',
            path='/'
        )
        http_session.cookies.set_cookie(steamCountry_cookie)
    
    if steam_cookies.get('webTradeEligibility'):
        webTradeEligibility_cookie = create_cookie(
            name='webTradeEligibility',
            value=steam_cookies['webTradeEligibility'],
            domain='steamcommunity.com',
            path='/'
        )
        http_session.cookies.set_cookie(webTradeEligibility_cookie)
    
    try:
        # CRITICAL: Visit Steam community homepage first to establish full session
        # This mimics what happens when you're already logged into Steam in your browser
        homepage_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        }
        
        homepage_response = http_session.get('https://steamcommunity.com/', headers=homepage_headers, timeout=10)
        time.sleep(0.3)  # Small delay
        
        # CRITICAL: Visit the market listing page to establish session and get Akamai cookies
        # Browsers do this automatically - they load the page, then make the API request
        from urllib.parse import quote
        listing_url = f'https://steamcommunity.com/market/listings/{appid}/{quote(market_hash_name)}'
        
        listing_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Referer': 'https://steamcommunity.com/',  # Add referer from homepage
        }
        
        listing_response = http_session.get(listing_url, headers=listing_headers, timeout=10)
        
        if listing_response.status_code != 200:
            print(f"Warning: Listing page returned {listing_response.status_code}")
        
        # Now make the price history request with the established session
        # CRITICAL: Match browser headers EXACTLY from the cURL command
        # Key insight: Browser uses text/html Accept header, NOT application/json!
        # This makes Steam think it's a browser navigation, not an API call
        api_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Referer': listing_url,  # Add Referer header - browser sends this when navigating from listing page
            'Sec-Fetch-Dest': 'document',  # Browser treats it as document navigation, not API
            'Sec-Fetch-Mode': 'navigate',  # Navigation mode, not cors/ajax
            'Sec-Fetch-Site': 'same-origin',  # Same origin since we're navigating from listing page
            'Sec-Fetch-User': '?1',  # User-initiated request
            'Upgrade-Insecure-Requests': '1',
            'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }
        
        time.sleep(0.5)  # Small delay like a browser would have
        response = http_session.get(url, params=params, headers=api_headers, timeout=10)
        
        if response.status_code != 200:
            print(f"Price history request failed: Status {response.status_code}, Response: {response.text[:200]}")
        
        if response.status_code == 200:
            # Check content type - might be JSON even with text/html Accept header
            content_type = response.headers.get('Content-Type', '').lower()
            
            try:
                # Try to parse as JSON first (Steam usually returns JSON even with text/html Accept)
                data = response.json()
                
                if 'prices' in data and len(data['prices']) > 0:
                    return jsonify(data)
                elif 'prices' in data and len(data['prices']) == 0:
                    return jsonify({'success': True, 'prices': []})
                else:
                    return jsonify(data)
                    
            except ValueError as e:
                # Not JSON - might be HTML or other format
                print(f"Error: Response is not JSON. Content-Type: {content_type}")
                
                # Check if it's HTML (Steam might return an error page)
                if 'text/html' in content_type or response.text.strip().startswith('<'):
                    # Try to extract JSON from HTML if it's embedded
                    json_match = re.search(r'\{[^{}]*"prices"[^{}]*\}', response.text, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(0))
                            return jsonify(data)
                        except:
                            pass
                    
                    return jsonify({
                        'error': 'Steam returned HTML instead of JSON. This may indicate an authentication issue.',
                        'steam_response': response.text[:500]
                    }), 500
                else:
                    return jsonify({
                        'error': f'Unexpected response format. Content-Type: {content_type}',
                        'steam_response': response.text[:500]
                    }), 500
        elif response.status_code == 400:
            # Steam returns 400 with [] for items with no history or invalid requests
            response_text = response.text.strip()
            print(f"Steam returned 400. Response: {response_text}")
            print(f"Full URL attempted: {response.url if hasattr(response, 'url') else url}")
            
            # Check if it's an empty array (no history) vs actual error
            if response_text == '[]':
                # For popular CS2 items, 400 with [] usually means account restrictions or cookie issues
                # Steam's price history API has strict requirements:
                # 1. Account must have made a purchase in the last year
                # 2. Steam Guard must be enabled
                # 3. Account must have market access
                # 4. Cookies must be fully authenticated (not just session cookies)
                print("Steam returned 400 with empty array - this usually indicates:")
                print("  1. Account restrictions (most common - account needs purchase in last year)")
                print("  2. Cookies are insufficient (need full authentication, not just session)")
                print("  3. Item has no price history (rare for popular CS2 items)")
                print("  4. Market hash name format mismatch")
                
                # Return error with helpful message
                return jsonify({
                    'error': 'Unable to fetch price history. Steam returned an empty response. This usually means your Steam account does not meet the requirements for accessing price history data.',
                    'prices': [],
                    'suggestion': 'Steam requires: 1) Account must have made a purchase in the last year, 2) Steam Guard enabled, 3) Market access enabled. Please verify your account meets these requirements at https://store.steampowered.com/account/',
                    'account_requirements': [
                        'Account must have made a purchase in the last year',
                        'Steam Guard must be enabled',
                        'Account must have market access enabled',
                        'Account must not be restricted or limited'
                    ]
                })
            else:
                # Might be an authentication issue or invalid request
                print("Steam returned 400 with non-empty response - possible authentication issue")
                return jsonify({
                    'error': f'Steam returned error: {response_text[:200]}. Please check your Steam cookies in Settings.',
                    'steam_response': response_text[:200]
                }), 400
        elif response.status_code == 403:
            return jsonify({
                'error': 'Access forbidden. Your Steam cookies may be invalid or expired. Please update them in Settings.',
                'steam_response': response.text[:200]
            }), 403
        else:
            return jsonify({
                'error': f'Failed to fetch price history. Status code: {response.status_code}',
                'steam_response': response.text[:200]
            }), 500
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request to Steam timed out. Please try again.'}), 504
    except requests.exceptions.RequestException as e:
        print(f"Request exception in price_history: {str(e)}")
        return jsonify({'error': f'Network error: {str(e)}'}), 500
    except Exception as e:
        print(f"Exception in price_history: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bp.route('/api/test-cookies', methods=['GET'])
def test_cookies():
    """Test if Steam cookies are working by trying to access Steam community"""
    try:
        steam_cookies = get_steam_cookies()
        
        if not steam_cookies.get('sessionid') or not steam_cookies.get('steamLoginSecure'):
            return jsonify({
                'valid': False,
                'error': 'Cookies not configured'
            }), 400
        
        # Validate token audience
        steamLoginSecure = steam_cookies.get('steamLoginSecure', '')
        is_valid, audience, error_msg = validate_steam_token_audience(steamLoginSecure)
        if not is_valid:
            return jsonify({
                'valid': False,
                'error': error_msg,
                'details': f'Token audience: {audience}. Please get fresh cookies from https://steamcommunity.com (not store.steampowered.com).'
            }), 400
        
        # Try to access a Steam page that requires authentication
        test_url = "https://steamcommunity.com/my/profile"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(test_url, headers=headers, cookies=steam_cookies, timeout=10, allow_redirects=False)
        
        # If we get redirected to login, cookies are invalid
        if response.status_code == 302 and 'login' in response.headers.get('Location', '').lower():
            return jsonify({
                'valid': False,
                'error': 'Cookies appear to be invalid or expired. Please update them.',
                'status_code': response.status_code
            })
        
        # Use a session to maintain cookies (same approach as price_history endpoint)
        test_session = requests.Session()
        test_session.cookies.set('sessionid', steam_cookies['sessionid'], domain='steamcommunity.com', path='/')
        test_session.cookies.set('steamLoginSecure', steam_cookies['steamLoginSecure'], domain='steamcommunity.com', path='/')
        
        # Add browserid if provided
        if steam_cookies.get('browserid'):
            test_session.cookies.set('browserid', steam_cookies['browserid'], domain='steamcommunity.com', path='/')
        
        # CRITICAL: Visit listing page first to get additional cookies (ak_bmsc, etc.)
        from urllib.parse import quote
        test_item_name = 'Danger Zone Case'
        listing_url = f'https://steamcommunity.com/market/listings/730/{quote(test_item_name)}'
        
        listing_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        }
        
        listing_response = test_session.get(listing_url, headers=listing_headers, timeout=10)
        
        time.sleep(0.5)
        
        # Now try price history with browser-like headers
        test_params = {
            'appid': '730',
            'market_hash_name': test_item_name,
            'currency': 1
        }
        test_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }
        
        ph_response = test_session.get(
            "https://steamcommunity.com/market/pricehistory/",
            params=test_params,
            headers=test_headers,
            timeout=10
        )
        
        if ph_response.status_code == 200:
            try:
                data = ph_response.json()
                if 'prices' in data and len(data['prices']) > 0:
                    return jsonify({
                        'valid': True,
                        'message': 'Cookies are working! Successfully fetched price history.',
                        'test_item': test_item_name,
                        'price_points': len(data['prices'])
                    })
                elif 'prices' in data:
                    return jsonify({
                        'valid': True,
                        'message': 'Cookies are valid, but no price history for test item.',
                        'test_item': test_item_name,
                        'price_points': 0
                    })
            except ValueError as e:
                # Not JSON - might be HTML
                return jsonify({
                    'valid': False,
                    'error': 'Steam returned HTML instead of JSON. Cookies may be invalid.',
                    'status_code': ph_response.status_code,
                    'response_preview': ph_response.text[:200]
                })
        
        if ph_response.status_code == 400:
            response_text = ph_response.text.strip()
            if response_text == '[]':
                return jsonify({
                    'valid': False,
                    'error': 'Cookies may be invalid, or your Steam account may not meet requirements for accessing price history.',
                    'details': 'Steam returned 400 with empty array. This usually means: 1) Cookies are expired/invalid, 2) Account restrictions, or 3) Account needs to have made a purchase in the last year.',
                    'status_code': ph_response.status_code,
                    'suggestion': 'Try copying fresh cookies from your browser while logged into Steam Community.'
                })
            else:
                return jsonify({
                    'valid': False,
                    'error': f'Steam returned 400 error: {response_text[:200]}',
                    'status_code': ph_response.status_code
                })
        
        return jsonify({
            'valid': False,
            'error': f'Unexpected response from Steam: {ph_response.status_code}',
            'status_code': ph_response.status_code,
            'response': ph_response.text[:200]
        })
        
    except Exception as e:
        return jsonify({
            'valid': False,
            'error': f'Error testing cookies: {str(e)}'
        }), 500

@bp.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page for configuring Steam cookies and API keys"""
    if request.method == 'POST':
        try:
            # Get data from form (always form data for this endpoint)
            cookie_string = request.form.get('cookieString', '').strip()
            sessionid = request.form.get('sessionid', '').strip()
            steamLoginSecure = request.form.get('steamLoginSecure', '').strip()
            browserid = request.form.get('browserid', '').strip()  # Optional
            steamCountry = request.form.get('steamCountry', '').strip()  # Optional
            webTradeEligibility = request.form.get('webTradeEligibility', '').strip()  # Optional
            steamapis_key = request.form.get('steamapis_key', '').strip()
            dark_mode = request.form.get('dark_mode', 'off') == 'on'
            
            # If cookie string is provided, parse it first
            if cookie_string:
                parsed_cookies = {}
                for cookie in cookie_string.split('; '):
                    if '=' in cookie:
                        name, value = cookie.split('=', 1)
                        parsed_cookies[name.strip()] = value.strip()
                
                # Use parsed cookies, fallback to form fields if not in cookie string
                sessionid = parsed_cookies.get('sessionid', sessionid)
                steamLoginSecure = parsed_cookies.get('steamLoginSecure', steamLoginSecure)
                browserid = parsed_cookies.get('browserid', browserid)
                steamCountry = parsed_cookies.get('steamCountry', steamCountry)
                webTradeEligibility = parsed_cookies.get('webTradeEligibility', webTradeEligibility)
            
            # Save settings to session
            if sessionid and steamLoginSecure:
                steam_cookies = {
                    'sessionid': sessionid,
                    'steamLoginSecure': steamLoginSecure
                }
                # Add optional cookies if provided
                if browserid:
                    steam_cookies['browserid'] = browserid
                if steamCountry:
                    steam_cookies['steamCountry'] = steamCountry
                if webTradeEligibility:
                    steam_cookies['webTradeEligibility'] = webTradeEligibility
                session['steam_cookies'] = steam_cookies
            else:
                # Clear cookies if empty
                session.pop('steam_cookies', None)
            
            if steamapis_key:
                session['steamapis_key'] = steamapis_key
            else:
                session.pop('steamapis_key', None)
            
            # Save dark mode preference
            session['dark_mode'] = dark_mode
            session.modified = True
            
            # Always return JSON for POST requests (AJAX)
            return jsonify({
                'message': 'Settings saved successfully',
                'has_cookies': bool(session.get('steam_cookies', {}).get('sessionid') and session.get('steam_cookies', {}).get('steamLoginSecure')),
                'has_api_key': bool(session.get('steamapis_key')),
                'dark_mode': dark_mode
            })
        except Exception as e:
            # Return JSON error response
            return jsonify({
                'error': f'Error saving settings: {str(e)}'
            }), 500
    
    # GET request - show current settings
    current_cookies = session.get('steam_cookies', {})
    current_api_key = session.get('steamapis_key', '')
    dark_mode = session.get('dark_mode', False)
    saved = request.args.get('saved', 0)
    
    return render_template('settings.html',
                         sessionid=current_cookies.get('sessionid', ''),
                         steamLoginSecure=current_cookies.get('steamLoginSecure', ''),
                         browserid=current_cookies.get('browserid', ''),
                         steamCountry=current_cookies.get('steamCountry', ''),
                         webTradeEligibility=current_cookies.get('webTradeEligibility', ''),
                         steamapis_key=current_api_key,
                         dark_mode=dark_mode,
                         saved=saved,
                         games=GAMES)
