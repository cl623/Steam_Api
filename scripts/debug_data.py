"""Debug script to check data format"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('data/market_data.db')

# Get first item with data
cursor = conn.cursor()
cursor.execute('''
    SELECT i.id, i.market_hash_name, COUNT(ph.id) as cnt
    FROM items i
    JOIN price_history ph ON i.id = ph.item_id
    WHERE i.game_id = '730'
    GROUP BY i.id
    HAVING COUNT(ph.id) >= 14
    ORDER BY cnt DESC
    LIMIT 1
''')
item = cursor.fetchone()
print(f"Item: {item[1]} (ID: {item[0]}, {item[2]} entries)")

# Get price history
df = pd.read_sql_query('''
    SELECT timestamp, price, volume
    FROM price_history
    WHERE item_id = ?
    ORDER BY timestamp ASC
    LIMIT 30
''', conn, params=(item[0],))

print(f"\nFirst 10 timestamps:")
print(df.head(10))
print(f"\nTotal rows: {len(df)}")

# Test timestamp parsing
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings('ignore')
    df['timestamp_parsed'] = pd.to_datetime(df['timestamp'], errors='coerce')

print(f"\nAfter parsing timestamps:")
print(f"Valid timestamps: {df['timestamp_parsed'].notna().sum()}")
print(f"NaN timestamps: {df['timestamp_parsed'].isna().sum()}")

# Test shift
df['future_price'] = df['price'].shift(-7)
print(f"\nAfter shift(-7):")
print(f"Rows with future_price: {df['future_price'].notna().sum()}")
print(f"Rows without future_price: {df['future_price'].isna().sum()}")

conn.close()
