"""Configuration constants for the Steam Market application"""

# Game IDs and Names
GAMES = {
    # '216150': 'MapleStory',  # Commented out - focusing on CS2 data collection
    '730': 'Counter-Strike 2'
}

# Default game ID
DEFAULT_GAME_ID = '730'  # Counter-Strike 2 (changed from MapleStory)

# Default values (can be overridden in settings)
DEFAULT_STEAMAPIS_KEY = "Oc7jRGOkx33t-hO_d9w_1ghv2io"

# Hardcoded test cookies - Updated via test_cookies.py
DEFAULT_STEAM_COOKIES = {
    'sessionid': 'cd378381e917696bf316041b',
    'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAxM18yNzg3M0Q1MV8xOTBCQiIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NjgyODU5MTAsICJuYmYiOiAxNzU5NTU3ODIwLCAiaWF0IjogMTc2ODE5NzgyMCwgImp0aSI6ICIwMDBCXzI3ODczRDY4XzVDNDlGIiwgIm9hdCI6IDE3NjgxMDAwMDIsICJydF9leHAiOiAxNzg2MzkxNzM0LCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiNzEuMTcyLjM3LjEwNyIsICJpcF9jb25maXJtZXIiOiAiNzEuMTcyLjM3LjEwNyIgfQ.ej1Sd8eBr7U1DLurjGsI9pMXjuGO22VHYl15O2SxrpdzdA1KH9XyMJ5ZVmefF5JF56kKsl_7dwndnUgCFYvYBg',
    'browserid': '68249548650920601',
    'steamCountry': 'US%7Cac6754462c6d54ce4276921dd1095a73',
    'webTradeEligibility': '%7B%22allowed%22%3A1%2C%22allowed_at_time%22%3A0%2C%22steamguard_required_days%22%3A15%2C%22new_device_cooldown_days%22%3A0%2C%22time_checked%22%3A1768100877%7D',
}
# Hardcoded test cookies - VERIFIED WORKING (tested 2026-01-12)
# These cookies successfully retrieve price history data (3,307 entries tested)
# 
# To get cookies:
# 1. Log into Steam in your browser
# 2. Go to: https://steamcommunity.com/market/listings/730/Danger%20Zone%20Case
# 3. Open Developer Tools (F12) → Network tab
# 4. Refresh the page
# 5. Find the request to /market/pricehistory/ in the Network tab
# 6. Click on it → Headers tab → Request Headers → Copy the "Cookie" header value
# 7. Use the cookie string with --cookie-string flag, or parse it and set individual cookies below
DEFAULT_STEAM_COOKIES = {
    'sessionid': 'cd378381e917696bf316041b',
    'steamLoginSecure': '76561198098290013%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAxM18yNzg3M0Q1MV8xOTBCQiIsICJzdWIiOiAiNzY1NjExOTgwOTgyOTAwMTMiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NjgyODU5MTAsICJuYmYiOiAxNzU5NTU3ODIwLCAiaWF0IjogMTc2ODE5NzgyMCwgImp0aSI6ICIwMDBCXzI3ODczRDY4XzVDNDlGIiwgIm9hdCI6IDE3NjgxMDAwMDIsICJydF9leHAiOiAxNzg2MzkxNzM0LCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiNzEuMTcyLjM3LjEwNyIsICJpcF9jb25maXJtZXIiOiAiNzEuMTcyLjM3LjEwNyIgfQ.ej1Sd8eBr7U1DLurjGsI9pMXjuGO22VHYl15O2SxrpdzdA1KH9XyMJ5ZVmefF5JF56kKsl_7dwndnUgCFYvYBg',
    'browserid': '68249548650920601',
    'steamCountry': 'US%7Cac6754462c6d54ce4276921dd1095a73',
    'webTradeEligibility': '%7B%22allowed%22%3A1%2C%22allowed_at_time%22%3A0%2C%22steamguard_required_days%22%3A15%2C%22new_device_cooldown_days%22%3A0%2C%22time_checked%22%3A1768100877%7D',
}

# Database path
import os
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'market_data.db')
