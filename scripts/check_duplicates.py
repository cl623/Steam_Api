import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

def check_data_quality():
    # Connect to the database
    conn = sqlite3.connect('market_data.db')
    cursor = conn.cursor()
    
    print("=== Data Quality Report ===\n")
    
    # 1. Check for duplicate entries
    print("1. Checking for duplicate entries...")
    cursor.execute('''
        SELECT ph.item_id, i.market_hash_name, ph.timestamp, ph.price, ph.volume, COUNT(*) as count
        FROM price_history ph
        JOIN items i ON ph.item_id = i.id
        GROUP BY ph.item_id, ph.timestamp, ph.price, ph.volume
        HAVING count > 1
    ''')
    
    duplicates = cursor.fetchall()
    if duplicates:
        print(f"\nFound {len(duplicates)} sets of duplicate entries:")
        print("\nItem Name | Timestamp | Price | Volume | Count")
        print("-" * 80)
        for item_id, item_name, timestamp, price, volume, count in duplicates:
            print(f"{item_name} | {timestamp} | {price} | {volume} | {count}")
    else:
        print("✓ No duplicate entries found")
    
    # 2. Check for data completeness
    print("\n2. Checking data completeness...")
    cursor.execute('''
        SELECT i.market_hash_name, COUNT(ph.id) as entry_count
        FROM items i
        LEFT JOIN price_history ph ON i.id = ph.item_id
        GROUP BY i.id
        HAVING entry_count = 0
    ''')
    
    items_without_history = cursor.fetchall()
    if items_without_history:
        print(f"\nFound {len(items_without_history)} items without price history:")
        for item_name, count in items_without_history:
            print(f"- {item_name}")
    else:
        print("✓ All items have price history entries")
    
    # 3. Check for price anomalies
    print("\n3. Checking for price anomalies...")
    cursor.execute('''
        WITH price_stats AS (
            SELECT 
                item_id,
                AVG(price) as avg_price,
                STDDEV(price) as stddev_price
            FROM price_history
            GROUP BY item_id
        )
        SELECT 
            i.market_hash_name,
            ph.timestamp,
            ph.price,
            ps.avg_price,
            ps.stddev_price,
            ABS(ph.price - ps.avg_price) / ps.stddev_price as z_score
        FROM price_history ph
        JOIN items i ON ph.item_id = i.id
        JOIN price_stats ps ON ph.item_id = ps.item_id
        WHERE ABS(ph.price - ps.avg_price) / ps.stddev_price > 3
        ORDER BY z_score DESC
        LIMIT 10
    ''')
    
    price_anomalies = cursor.fetchall()
    if price_anomalies:
        print("\nFound potential price anomalies (prices > 3 standard deviations from mean):")
        print("\nItem Name | Timestamp | Price | Average Price | Z-Score")
        print("-" * 100)
        for item_name, timestamp, price, avg_price, stddev, z_score in price_anomalies:
            print(f"{item_name} | {timestamp} | {price:.2f} | {avg_price:.2f} | {z_score:.2f}")
    else:
        print("✓ No significant price anomalies found")
    
    # 4. Check for time gaps
    print("\n4. Checking for time gaps in price history...")
    cursor.execute('''
        WITH time_gaps AS (
            SELECT 
                item_id,
                timestamp,
                LAG(timestamp) OVER (PARTITION BY item_id ORDER BY timestamp) as prev_timestamp
            FROM price_history
        )
        SELECT 
            i.market_hash_name,
            tg.timestamp,
            tg.prev_timestamp,
            ROUND((JULIANDAY(tg.timestamp) - JULIANDAY(tg.prev_timestamp)) * 24 * 60) as gap_minutes
        FROM time_gaps tg
        JOIN items i ON tg.item_id = i.id
        WHERE tg.prev_timestamp IS NOT NULL
        AND (JULIANDAY(tg.timestamp) - JULIANDAY(tg.prev_timestamp)) * 24 * 60 > 60
        ORDER BY gap_minutes DESC
        LIMIT 10
    ''')
    
    time_gaps = cursor.fetchall()
    if time_gaps:
        print("\nFound significant time gaps (> 60 minutes) in price history:")
        print("\nItem Name | Current Timestamp | Previous Timestamp | Gap (minutes)")
        print("-" * 100)
        for item_name, curr_time, prev_time, gap in time_gaps:
            print(f"{item_name} | {curr_time} | {prev_time} | {gap}")
    else:
        print("✓ No significant time gaps found")
    
    # 5. Check for data freshness
    print("\n5. Checking data freshness...")
    cursor.execute('''
        SELECT 
            i.market_hash_name,
            MAX(ph.timestamp) as last_update,
            ROUND((JULIANDAY('now') - JULIANDAY(MAX(ph.timestamp))) * 24) as hours_old
        FROM items i
        JOIN price_history ph ON i.id = ph.item_id
        GROUP BY i.id
        HAVING hours_old > 24
        ORDER BY hours_old DESC
        LIMIT 10
    ''')
    
    stale_data = cursor.fetchall()
    if stale_data:
        print("\nFound items with stale data (> 24 hours old):")
        print("\nItem Name | Last Update | Hours Old")
        print("-" * 80)
        for item_name, last_update, hours_old in stale_data:
            print(f"{item_name} | {last_update} | {hours_old}")
    else:
        print("✓ All items have recent price history")
    
    # 6. Check for volume anomalies
    print("\n6. Checking for volume anomalies...")
    cursor.execute('''
        WITH volume_stats AS (
            SELECT 
                item_id,
                AVG(volume) as avg_volume,
                STDDEV(volume) as stddev_volume
            FROM price_history
            GROUP BY item_id
        )
        SELECT 
            i.market_hash_name,
            ph.timestamp,
            ph.volume,
            vs.avg_volume,
            vs.stddev_volume,
            ABS(ph.volume - vs.avg_volume) / vs.stddev_volume as z_score
        FROM price_history ph
        JOIN items i ON ph.item_id = i.id
        JOIN volume_stats vs ON ph.item_id = vs.item_id
        WHERE ABS(ph.volume - vs.avg_volume) / vs.stddev_volume > 3
        ORDER BY z_score DESC
        LIMIT 10
    ''')
    
    volume_anomalies = cursor.fetchall()
    if volume_anomalies:
        print("\nFound potential volume anomalies (volumes > 3 standard deviations from mean):")
        print("\nItem Name | Timestamp | Volume | Average Volume | Z-Score")
        print("-" * 100)
        for item_name, timestamp, volume, avg_volume, stddev, z_score in volume_anomalies:
            print(f"{item_name} | {timestamp} | {volume} | {avg_volume:.2f} | {z_score:.2f}")
    else:
        print("✓ No significant volume anomalies found")
    
    # Print overall statistics
    cursor.execute('SELECT COUNT(*) FROM items')
    total_items = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM price_history')
    total_entries = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT COUNT(DISTINCT item_id) 
        FROM price_history
    ''')
    items_with_history = cursor.fetchone()[0]
    
    print("\n=== Overall Statistics ===")
    print(f"Total items in database: {total_items}")
    print(f"Items with price history: {items_with_history}")
    print(f"Total price history entries: {total_entries}")
    if total_items > 0:
        print(f"Average entries per item: {total_entries/total_items:.2f}")

if __name__ == "__main__":
    check_data_quality() 