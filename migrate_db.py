import sqlite3
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('migration.log'),
        logging.StreamHandler()
    ]
)

def migrate_database():
    """Add app_id column to items table if it doesn't exist."""
    try:
        with sqlite3.connect('market_data.db') as conn:
            cursor = conn.cursor()
            
            # Check if app_id column exists
            cursor.execute("PRAGMA table_info(items)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'app_id' not in columns:
                logging.info("Adding app_id column to items table...")
                cursor.execute('ALTER TABLE items ADD COLUMN app_id TEXT')
                
                # Update existing items with default app_id based on game_id
                cursor.execute('''
                    UPDATE items 
                    SET app_id = CASE 
                        WHEN game_id = 'csgo' THEN '730'
                        WHEN game_id = 'maplestory' THEN '216150'
                        ELSE '730'
                    END
                    WHERE app_id IS NULL
                ''')
                
                conn.commit()
                logging.info("Successfully added app_id column and updated existing items")
            else:
                logging.info("app_id column already exists in items table")
                
    except Exception as e:
        logging.error(f"Error during migration: {str(e)}")
        raise

if __name__ == "__main__":
    migrate_database() 