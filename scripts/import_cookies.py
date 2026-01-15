#!/usr/bin/env python3
"""
Cookie Import Script - Update app/config.py with cookies from cookie string or individual values.

This script provides an easy way to update cookies in config.py without manually editing the file.

Usage:
    # From cookie string (easiest):
    python scripts/import_cookies.py --cookie-string "sessionid=...; steamLoginSecure=...; ..."
    
    # From individual cookies:
    python scripts/import_cookies.py --sessionid YOUR_SESSIONID --steam-login-secure YOUR_LOGIN_SECURE
    
    # From environment variables:
    export STEAM_COOKIE_STRING="sessionid=...; steamLoginSecure=..."
    python scripts/import_cookies.py
"""

import sys
import os
import argparse
import re

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_cookie_string(cookie_string):
    """Parse a cookie string into a dictionary."""
    cookies = {}
    for cookie in cookie_string.split('; '):
        if '=' in cookie:
            name, value = cookie.split('=', 1)
            cookies[name.strip()] = value.strip()
    return cookies


def update_config_file(cookies, config_path=None):
    """Update app/config.py with new cookies."""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'config.py')
    
    if not os.path.exists(config_path):
        print(f"[ERROR] Config file not found: {config_path}")
        return False
    
    # Read current config
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract required cookies
    sessionid = cookies.get('sessionid', '')
    steamLoginSecure = cookies.get('steamLoginSecure', '')
    
    if not sessionid or not steamLoginSecure:
        print("[ERROR] Missing required cookies: sessionid and steamLoginSecure are required")
        return False
    
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
        insert_replacement = r"\1\n\n# Hardcoded test cookies - Updated via import_cookies.py\nDEFAULT_STEAM_COOKIES = {{\n{}\n}}\n".format('\n'.join(cookie_dict_lines))
        new_content = re.sub(insert_pattern, insert_replacement, content)
    
    # Write updated config
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"[SUCCESS] Updated {config_path} with new cookies")
    print(f"  - sessionid: {sessionid[:20]}...")
    print(f"  - steamLoginSecure: {steamLoginSecure[:30]}...")
    if cookies.get('browserid'):
        print(f"  - browserid: {cookies['browserid']}")
    if cookies.get('steamCountry'):
        print(f"  - steamCountry: {cookies['steamCountry'][:30]}...")
    if cookies.get('webTradeEligibility'):
        print(f"  - webTradeEligibility: {cookies['webTradeEligibility'][:30]}...")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Import Steam cookies into app/config.py',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # From cookie string (easiest):
  python scripts/import_cookies.py --cookie-string "sessionid=abc; steamLoginSecure=xyz; ..."
  
  # From individual cookies:
  python scripts/import_cookies.py --sessionid abc123 --steam-login-secure 7656119...
  
  # From environment variable:
  export STEAM_COOKIE_STRING="sessionid=...; steamLoginSecure=..."
  python scripts/import_cookies.py
        """
    )
    
    parser.add_argument('--cookie-string',
                       help='Full cookie string from browser (will parse all cookies)',
                       default=os.getenv('STEAM_COOKIE_STRING', ''))
    parser.add_argument('--sessionid',
                       help='Steam session ID cookie',
                       default=os.getenv('STEAM_SESSIONID', ''))
    parser.add_argument('--steam-login-secure',
                       help='Steam login secure cookie',
                       default=os.getenv('STEAM_LOGIN_SECURE', ''))
    parser.add_argument('--browserid',
                       help='Optional browser ID cookie',
                       default=os.getenv('STEAM_BROWSERID', ''))
    parser.add_argument('--steam-country',
                       help='Optional steamCountry cookie',
                       default=os.getenv('STEAM_COUNTRY', ''))
    parser.add_argument('--web-trade-eligibility',
                       help='Optional webTradeEligibility cookie',
                       default=os.getenv('STEAM_WEB_TRADE_ELIGIBILITY', ''))
    parser.add_argument('--config-path',
                       help='Path to config.py file (default: app/config.py)',
                       default=None)
    
    args = parser.parse_args()
    
    # Parse cookies
    cookies = {}
    
    if args.cookie_string:
        # Parse from cookie string
        parsed = parse_cookie_string(args.cookie_string)
        cookies.update(parsed)
        print(f"[INFO] Parsed {len(parsed)} cookies from cookie string")
    
    # Override with individual arguments if provided
    if args.sessionid:
        cookies['sessionid'] = args.sessionid
    if args.steam_login_secure:
        cookies['steamLoginSecure'] = args.steam_login_secure
    if args.browserid:
        cookies['browserid'] = args.browserid
    if args.steam_country:
        cookies['steamCountry'] = args.steam_country
    if args.web_trade_eligibility:
        cookies['webTradeEligibility'] = args.web_trade_eligibility
    
    # Validate required cookies
    if not cookies.get('sessionid') or not cookies.get('steamLoginSecure'):
        print("[ERROR] Missing required cookies: sessionid and steamLoginSecure are required")
        print()
        print("Please provide cookies using one of these methods:")
        print("  1. Cookie string: --cookie-string \"sessionid=...; steamLoginSecure=...\"")
        print("  2. Individual cookies: --sessionid ... --steam-login-secure ...")
        print("  3. Environment variables: export STEAM_COOKIE_STRING=\"...\"")
        sys.exit(1)
    
    # Update config file
    success = update_config_file(cookies, args.config_path)
    
    if success:
        print()
        print("[SUCCESS] Cookies imported successfully!")
        print("  The collector and Flask app will now use these cookies.")
        print("  You can test them with: python scripts/test_cookies.py --use-config")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
