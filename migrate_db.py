#!/usr/bin/env python3
"""
Database migration script to add social authentication fields
"""
import sqlite3
import os
import time
from pathlib import Path

def migrate_database():
    """Add social authentication fields to existing database"""
    db_path = "qr.db"
    
    if not os.path.exists(db_path):
        print("No existing database found. New database will be created with all fields.")
        return True
    
    print(f"Migrating database: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get current table schema
        cursor.execute("PRAGMA table_info(user)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"Current columns: {columns}")
        
        # Add new columns if they don't exist
        new_columns = [
            ("email", "TEXT"),
            ("full_name", "TEXT"),
            ("profile_picture", "TEXT"),
            ("social_provider", "TEXT"),
            ("social_id", "TEXT"),
            ("social_data", "TEXT")
        ]
        
        for column_name, column_type in new_columns:
            if column_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE user ADD COLUMN {column_name} {column_type}")
                    print(f"✓ Added column: {column_name}")
                except sqlite3.OperationalError as e:
                    print(f"✗ Failed to add column {column_name}: {e}")
        
        # Create indexes for new columns
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_email ON user(email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_social_id ON user(social_id)")
            print("✓ Created indexes")
        except sqlite3.OperationalError as e:
            print(f"⚠ Index creation warning: {e}")
        
        conn.commit()
        conn.close()
        
        print("✓ Database migration completed successfully")
        return True
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return False

def backup_database():
    """Create a backup of the existing database"""
    db_path = "qr.db"
    
    if not os.path.exists(db_path):
        return True
    
    backup_path = f"qr_backup_{int(time.time())}.db"
    
    try:
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✓ Database backed up to: {backup_path}")
        return True
    except Exception as e:
        print(f"✗ Backup failed: {e}")
        return False

def verify_migration():
    """Verify that the migration was successful"""
    db_path = "qr.db"
    
    if not os.path.exists(db_path):
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check that all new columns exist
        cursor.execute("PRAGMA table_info(user)")
        columns = [row[1] for row in cursor.fetchall()]
        
        required_columns = ['email', 'full_name', 'profile_picture', 'social_provider', 'social_id', 'social_data']
        
        missing_columns = [col for col in required_columns if col not in columns]
        
        if missing_columns:
            print(f"✗ Missing columns: {missing_columns}")
            return False
        
        print("✓ All required columns present")
        
        # Test that we can insert a record with social auth fields
        cursor.execute("""
            INSERT OR IGNORE INTO user 
            (username, password_hash, email, social_provider, social_id, created_at) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("test_social", None, "test@example.com", "google", "123456", "2024-01-01T00:00:00"))
        
        conn.commit()
        conn.close()
        
        print("✓ Migration verification successful")
        return True
        
    except Exception as e:
        print(f"✗ Migration verification failed: {e}")
        return False

def main():
    """Run the migration"""
    print("=== Database Migration for Social Authentication ===\n")
    
    # Import time here to avoid issues if not available
    import time
    
    # Step 1: Backup existing database
    print("Step 1: Creating backup...")
    if not backup_database():
        print("Backup failed, but continuing with migration...")
    
    # Step 2: Run migration
    print("\nStep 2: Running migration...")
    if not migrate_database():
        print("Migration failed!")
        return 1
    
    # Step 3: Verify migration
    print("\nStep 3: Verifying migration...")
    if not verify_migration():
        print("Migration verification failed!")
        return 1
    
    print("\n🎉 Migration completed successfully!")
    print("\nYou can now run the application with social authentication support.")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
