#!/usr/bin/env python3
"""
Migration script to optimize database schema for machine learning.

This script adds:
1. Normalized timestamp column (ISO format datetime)
2. Pre-computed ML feature columns
3. Optimized indexes for ML queries
4. Materialized view for ML features
"""

import sqlite3
import os
import sys
from datetime import datetime
import re

# Fix Unicode encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def parse_steam_timestamp(timestamp_str):
    """Parse Steam timestamp format to datetime object"""
    try:
        # Steam format: "Dec 06 2018 01: +0"
        clean_timestamp = re.sub(r'\s+\+\d+$', '', timestamp_str).strip()
        parts = re.match(r'(\w+)\s+(\d+)\s+(\d+)\s+(\d+):', clean_timestamp)
        if parts:
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            month = month_names.index(parts.group(1)) + 1
            day = int(parts.group(2))
            year = int(parts.group(3))
            hour = int(parts.group(4))
            return datetime(year, month, day, hour)
    except (ValueError, AttributeError, IndexError):
        pass
    return None

def migrate_database(db_path):
    """Perform database migration for ML optimizations"""
    print(f"Migrating database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Step 1: Add normalized timestamp column
        print("\n[1/6] Adding normalized timestamp column...")
        try:
            cursor.execute('ALTER TABLE price_history ADD COLUMN timestamp_normalized TIMESTAMP')
            print("  ✓ Added timestamp_normalized column")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("  ✓ Column already exists, skipping")
            else:
                raise
        
        # Step 2: Add ML feature columns
        print("\n[2/6] Adding ML feature columns...")
        feature_columns = [
            ('price_ma7', 'REAL'),
            ('price_ma30', 'REAL'),
            ('price_std7', 'REAL'),
            ('volume_ma7', 'REAL'),
            ('price_change_1d', 'REAL'),
            ('price_change_7d', 'REAL'),
            ('volume_change_1d', 'REAL'),
        ]
        
        for col_name, col_type in feature_columns:
            try:
                cursor.execute(f'ALTER TABLE price_history ADD COLUMN {col_name} {col_type}')
                print(f"  ✓ Added {col_name} column")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    print(f"  ✓ Column {col_name} already exists, skipping")
                else:
                    raise
        
        # Step 3: Populate normalized timestamps
        print("\n[3/6] Populating normalized timestamps...")
        cursor.execute('SELECT COUNT(*) FROM price_history WHERE timestamp_normalized IS NULL')
        null_count = cursor.fetchone()[0]
        
        if null_count > 0:
            print(f"  Processing {null_count} rows...")
            cursor.execute('SELECT id, timestamp FROM price_history WHERE timestamp_normalized IS NULL')
            rows = cursor.fetchall()
            
            updated = 0
            for row_id, timestamp_str in rows:
                dt = parse_steam_timestamp(timestamp_str)
                if dt:
                    cursor.execute(
                        'UPDATE price_history SET timestamp_normalized = ? WHERE id = ?',
                        (dt.isoformat(), row_id)
                    )
                    updated += 1
                    if updated % 1000 == 0:
                        print(f"    Updated {updated}/{null_count} rows...")
                        conn.commit()
            
            conn.commit()
            print(f"  ✓ Updated {updated} normalized timestamps")
        else:
            print("  ✓ All timestamps already normalized")
        
        # Step 4: Create optimized indexes
        print("\n[4/6] Creating optimized indexes...")
        indexes = [
            ('idx_price_history_normalized', 
             'price_history(item_id, timestamp_normalized)'),
            ('idx_ml_item_timestamp', 
             'price_history(item_id, timestamp_normalized, price, volume)'),
        ]
        
        for idx_name, idx_def in indexes:
            try:
                cursor.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}')
                print(f"  ✓ Created index {idx_name}")
            except sqlite3.OperationalError as e:
                print(f"  ⚠ Error creating index {idx_name}: {e}")
        
        # Step 5: Create item statistics table
        print("\n[5/6] Creating item statistics table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS item_statistics (
                item_id INTEGER PRIMARY KEY,
                mean_price REAL,
                std_price REAL,
                min_price REAL,
                max_price REAL,
                mean_volume REAL,
                price_volatility REAL,
                trend_7d REAL,
                trend_30d REAL,
                last_updated TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items (id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_item_stats_game ON item_statistics(item_id)')
        print("  ✓ Created item_statistics table")
        
        # Step 6: Create ML features view (using window functions)
        print("\n[6/6] Creating ML features view...")
        # Note: SQLite doesn't support LEAD/LAG window functions in older versions
        # We'll create a simpler view that can be enhanced later
        cursor.execute('DROP VIEW IF EXISTS ml_features')
        cursor.execute('''
            CREATE VIEW IF NOT EXISTS ml_features AS
            SELECT 
                ph.id,
                ph.item_id,
                ph.timestamp_normalized,
                ph.price,
                ph.volume,
                ph.price_ma7,
                ph.price_ma30,
                ph.price_std7,
                ph.volume_ma7,
                ph.price_change_1d,
                ph.price_change_7d,
                ph.volume_change_1d,
                i.game_id,
                i.market_hash_name
            FROM price_history ph
            JOIN items i ON ph.item_id = i.id
            WHERE ph.timestamp_normalized IS NOT NULL
            ORDER BY ph.item_id, ph.timestamp_normalized
        ''')
        print("  ✓ Created ml_features view")
        
        conn.commit()
        print("\n✓ Migration completed successfully!")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

def compute_features_for_item(cursor, item_id):
    """Compute ML features for a specific item"""
    # Get price history ordered by timestamp
    cursor.execute('''
        SELECT id, timestamp_normalized, price, volume
        FROM price_history
        WHERE item_id = ? AND timestamp_normalized IS NOT NULL
        ORDER BY timestamp_normalized ASC
    ''', (item_id,))
    
    rows = cursor.fetchall()
    if len(rows) < 30:  # Need at least 30 days for MA30
        return
    
    # Compute features using window functions
    # Note: SQLite doesn't support window functions in UPDATE, so we'll do it in Python
    prices = [row[2] for row in rows]
    volumes = [row[3] for row in rows]
    ids = [row[0] for row in rows]
    
    # Compute rolling statistics
    for i in range(len(rows)):
        updates = {}
        
        # MA7 and MA30
        if i >= 6:  # Need at least 7 data points
            updates['price_ma7'] = sum(prices[max(0, i-6):i+1]) / min(7, i+1)
            updates['volume_ma7'] = sum(volumes[max(0, i-6):i+1]) / min(7, i+1)
        if i >= 6:
            updates['price_std7'] = (
                sum((p - updates['price_ma7'])**2 for p in prices[max(0, i-6):i+1]) / min(7, i+1)
            ) ** 0.5
        if i >= 29:  # Need at least 30 data points
            updates['price_ma30'] = sum(prices[max(0, i-29):i+1]) / min(30, i+1)
        
        # Price changes
        if i > 0:
            updates['price_change_1d'] = prices[i] - prices[i-1]
        if i >= 7:
            updates['price_change_7d'] = prices[i] - prices[i-7]
        if i > 0:
            updates['volume_change_1d'] = volumes[i] - volumes[i-1]
        
        # Update row
        if updates:
            set_clause = ', '.join(f'{k} = ?' for k in updates.keys())
            values = list(updates.values()) + [ids[i]]
            cursor.execute(f'''
                UPDATE price_history 
                SET {set_clause}
                WHERE id = ?
            ''', values)

def compute_all_features(db_path):
    """Compute ML features for all items"""
    print("\nComputing ML features for all items...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT DISTINCT item_id FROM price_history')
        item_ids = [row[0] for row in cursor.fetchall()]
        
        print(f"Processing {len(item_ids)} items...")
        for i, item_id in enumerate(item_ids):
            compute_features_for_item(cursor, item_id)
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(item_ids)} items...")
                conn.commit()
        
        conn.commit()
        print("✓ Feature computation completed!")
    except Exception as e:
        conn.rollback()
        print(f"✗ Feature computation failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate database schema for ML optimization')
    parser.add_argument('--db-path', default='data/market_data.db',
                       help='Path to database file (relative to project root or absolute)')
    parser.add_argument('--compute-features', action='store_true',
                       help='Compute ML features for all items (slow)')
    
    args = parser.parse_args()
    
    # Get project root (parent of scripts directory)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Handle database path
    if os.path.isabs(args.db_path):
        # If absolute path provided, use it directly
        db_path = args.db_path
    else:
        # If relative path, join with project root
        # Remove leading 'data/' if present to avoid duplication
        if args.db_path.startswith('data/'):
            db_path = os.path.join(project_root, args.db_path)
        else:
            db_path = os.path.join(project_root, args.db_path)
    
    print(f"Project root: {project_root}")
    print(f"Database path: {db_path}")
    
    if migrate_database(db_path):
        if args.compute_features:
            compute_all_features(db_path)
        else:
            print("\nNote: ML features not computed. Run with --compute-features to compute them.")
            print("      This is optional and can be done later or incrementally.")
