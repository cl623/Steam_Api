# Cookie Setup Guide - User-Friendly Workflow

This guide explains the easiest ways to provide Steam cookies for the application.

## 🎯 Quick Start (Recommended)

### Method 1: Cookie String (Easiest)

1. **Get Cookie String from Browser:**
   - ⚠️ **CRITICAL:** Make sure you're on `steamcommunity.com` (NOT `store.steampowered.com`)
   
   **Option A - From Market Listing Page:**
   - Go to [Steam Market](https://steamcommunity.com/market/listings/730/Danger%20Zone%20Case) in your browser (while logged in)
   - Open Developer Tools (F12) → **Network** tab
   - Refresh the page (F5)
   - Find the request to `/market/pricehistory/` in the Network tab
   - Click on it → **Headers** tab → Scroll to **Request Headers**
   - Copy the entire `Cookie:` header value
   
   **Option B - From Direct API URL (Easier!):**
   - Open [this direct API URL](https://steamcommunity.com/market/pricehistory/?appid=730&market_hash_name=Danger%20Zone%20Case&currency=1) in your browser (while logged in)
   - Open Developer Tools (F12) → **Network** tab
   - Find the request to `/market/pricehistory/` (it should be the first/only request)
   - Click on it → **Headers** tab → Scroll to **Request Headers**
   - Copy the entire `Cookie:` header value
   
   - **Important:** The token must have audience `"web:community"`, not `"web:store"`

2. **Use in Settings Page:**
   - Go to Settings page in the web app
   - Paste the cookie string in the "Cookie String" field
   - Click "Parse Cookie String" - it will automatically extract all cookies
   - Click "Save Settings"

3. **Or Use Import Script:**
   ```bash
   python scripts/import_cookies.py --cookie-string "sessionid=...; steamLoginSecure=...; ..."
   ```

### Method 2: Individual Cookies

If you prefer to enter cookies individually:

1. **Get Cookies from Browser:**
   - Go to [Steam Community](https://steamcommunity.com) in your browser
   - Open Developer Tools (F12) → **Application** tab → **Cookies** → `https://steamcommunity.com`
   - Copy values for:
     - `sessionid` (required)
     - `steamLoginSecure` (required)
     - `browserid` (optional, but recommended)
     - `steamCountry` (optional, but recommended)
     - `webTradeEligibility` (optional, but recommended)

2. **Enter in Settings Page:**
   - Go to Settings page
   - Enter cookies in individual fields
   - Click "Save Settings"

## 📋 Available Methods

### 1. Web Settings Page (Session-based)
- **Location:** Settings page in web app
- **Storage:** Flask session (temporary, per browser session)
- **Best for:** Quick testing, temporary use
- **How:** Paste cookie string or enter individual cookies

### 2. Config File (Persistent)
- **Location:** `app/config.py`
- **Storage:** File-based (persistent across restarts)
- **Best for:** Production use, collector script
- **How:** Use import script or edit manually

### 3. Environment Variables
- **Storage:** System environment variables
- **Best for:** Server deployments, CI/CD
- **How:** Set `STEAM_COOKIE_STRING` or individual cookie variables

### 4. Command-Line Arguments
- **Best for:** Scripts, one-time use
- **How:** Pass `--cookie-string` or individual cookie arguments

## 🔧 Import Script Usage

The `scripts/import_cookies.py` script makes it easy to update `app/config.py`:

```bash
# From cookie string (easiest):
python scripts/import_cookies.py --cookie-string "sessionid=...; steamLoginSecure=...; ..."

# From individual cookies:
python scripts/import_cookies.py --sessionid YOUR_SESSIONID --steam-login-secure YOUR_LOGIN_SECURE

# From environment variable:
export STEAM_COOKIE_STRING="sessionid=...; steamLoginSecure=..."
python scripts/import_cookies.py
```

## ✅ Testing Cookies

After setting cookies, test them:

```bash
# Test with cookie string:
python scripts/test_cookies.py --cookie-string "sessionid=...; steamLoginSecure=..."

# Test with config file:
python scripts/test_cookies.py --use-config

# Test with individual cookies:
python scripts/test_cookies.py --sessionid ... --steam-login-secure ...
```

Or use the "Test Cookies" button in the Settings page.

## 📝 Cookie Priority

The application checks cookies in this order:

1. **Flask session** (from Settings page) - highest priority
2. **Environment variables** (`STEAM_COOKIE_STRING`, `STEAM_SESSIONID`, etc.)
3. **Config file** (`app/config.py` - `DEFAULT_STEAM_COOKIES`)

## 🔐 Security Notes

- Cookies are stored in Flask session (temporary) or config file (persistent)
- Session cookies expire when you close the browser
- Config file cookies persist until updated
- Never commit cookies to version control (use `.gitignore`)

## 🎨 Settings Page Features

- **Cookie String Parser:** Paste full cookie string, automatically extracts all cookies
- **Individual Fields:** Enter cookies manually if preferred
- **Test Button:** Test cookies before saving
- **Status Badges:** Visual indicators for configured cookies
- **Auto-fill:** Parsed cookies automatically populate individual fields

## 💡 Tips

1. **Cookie String Method is Fastest:** Just copy the Cookie header from Network tab
2. **Use Test Button:** Always test cookies before saving
3. **Update Regularly:** Cookies expire, update them when you get 400/401 errors
4. **Include Optional Cookies:** `browserid`, `steamCountry`, and `webTradeEligibility` improve success rate
