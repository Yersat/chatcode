#!/usr/bin/env python3
"""
Migration script to move data from SQLite to PostgreSQL
"""
import os
import sys
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine, select, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the User model from the main app
sys.path.append('.')
from app import User

def get_sqlite_data():
    """Extract all data from SQLite database"""
    sqlite_path = "qr.db"
    
    if not os.path.exists(sqlite_path):
        print("❌ SQLite database not found at qr.db")
        return []
    
    print(f"📖 Reading data from SQLite database: {sqlite_path}")
    
    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row  # This enables column access by name
        cursor = conn.cursor()
        
        # Get all users
        cursor.execute("SELECT * FROM user")
        users = cursor.fetchall()
        
        # Convert to list of dictionaries
        user_data = []
        for user in users:
            user_dict = dict(user)
            user_data.append(user_dict)
        
        conn.close()
        
        print(f"✅ Found {len(user_data)} users in SQLite database")
        return user_data
        
    except Exception as e:
        print(f"❌ Error reading SQLite database: {e}")
        return []

def setup_postgresql():
    """Set up PostgreSQL database and tables"""
    db_url = os.getenv("DB_URL")
    
    if not db_url or not (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
        print("❌ PostgreSQL DB_URL not found in environment variables")
        print("Please set DB_URL to a PostgreSQL connection string in your .env file")
        return None
    
    print(f"🔗 Connecting to PostgreSQL: {db_url.split('@')[1] if '@' in db_url else 'localhost'}")
    
    try:
        # Create engine with PostgreSQL-specific settings
        engine = create_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=300,
            echo=False
        )
        
        # Test connection
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
        
        print("✅ PostgreSQL connection successful")
        
        # Create all tables
        print("🏗️  Creating database tables...")
        SQLModel.metadata.create_all(engine)
        print("✅ Database tables created successfully")
        
        return engine
        
    except Exception as e:
        print(f"❌ Error connecting to PostgreSQL: {e}")
        print("\nTroubleshooting tips:")
        print("1. Make sure PostgreSQL is running")
        print("2. Check your DB_URL connection string")
        print("3. Verify database credentials and permissions")
        print("4. Ensure the database exists")
        return None

def migrate_data(engine, sqlite_data):
    """Migrate data from SQLite to PostgreSQL"""
    if not sqlite_data:
        print("⚠️  No data to migrate")
        return True
    
    print(f"🚀 Starting data migration for {len(sqlite_data)} users...")
    
    try:
        with Session(engine) as session:
            # Clear existing data (optional - comment out if you want to preserve existing data)
            print("🧹 Clearing existing data...")
            session.exec(text("DELETE FROM \"user\""))
            session.commit()
            
            # Migrate users
            migrated_count = 0
            for user_data in sqlite_data:
                try:
                    # Create User object
                    user = User(
                        id=user_data.get('id'),
                        username=user_data.get('username'),
                        password_hash=user_data.get('password_hash'),
                        phone_e164=user_data.get('phone_e164'),
                        preset_text=user_data.get('preset_text'),
                        is_admin=bool(user_data.get('is_admin', False)),
                        is_active=bool(user_data.get('is_active', True)),
                        created_at=user_data.get('created_at'),
                        last_login=user_data.get('last_login'),
                        email=user_data.get('email'),
                        full_name=user_data.get('full_name'),
                        profile_picture=user_data.get('profile_picture'),
                        social_provider=user_data.get('social_provider'),
                        social_id=user_data.get('social_id'),
                        social_data=user_data.get('social_data')
                    )
                    
                    session.add(user)
                    migrated_count += 1
                    
                except Exception as e:
                    print(f"⚠️  Error migrating user {user_data.get('username', 'unknown')}: {e}")
                    continue
            
            # Commit all changes
            session.commit()
            print(f"✅ Successfully migrated {migrated_count} users to PostgreSQL")
            
            # Reset sequence for auto-increment ID
            try:
                max_id = session.exec(text("SELECT MAX(id) FROM \"user\"")).first()
                if max_id:
                    session.exec(text(f"ALTER SEQUENCE user_id_seq RESTART WITH {max_id + 1}"))
                    session.commit()
                    print("✅ Reset ID sequence")
            except Exception as e:
                print(f"⚠️  Could not reset ID sequence: {e}")
            
            return True
            
    except Exception as e:
        print(f"❌ Error during data migration: {e}")
        return False

def verify_migration(engine, original_count):
    """Verify that the migration was successful"""
    print("🔍 Verifying migration...")
    
    try:
        with Session(engine) as session:
            users = session.exec(select(User)).all()
            migrated_count = len(users)
            
            print(f"📊 Migration verification:")
            print(f"   Original SQLite records: {original_count}")
            print(f"   Migrated PostgreSQL records: {migrated_count}")
            
            if migrated_count == original_count:
                print("✅ Migration verification successful - all records migrated")
                
                # Show sample of migrated data
                if users:
                    sample_user = users[0]
                    print(f"📋 Sample migrated user:")
                    print(f"   ID: {sample_user.id}")
                    print(f"   Username: {sample_user.username}")
                    print(f"   Phone: {sample_user.phone_e164}")
                    print(f"   Admin: {sample_user.is_admin}")
                    print(f"   Created: {sample_user.created_at}")
                
                return True
            else:
                print(f"⚠️  Migration verification failed - record count mismatch")
                return False
                
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        return False

def backup_sqlite():
    """Create a backup of the SQLite database"""
    sqlite_path = "qr.db"
    
    if not os.path.exists(sqlite_path):
        return True
    
    backup_name = f"qr_backup_before_postgresql_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    
    try:
        import shutil
        shutil.copy2(sqlite_path, backup_name)
        print(f"✅ SQLite database backed up to: {backup_name}")
        return True
    except Exception as e:
        print(f"❌ Failed to backup SQLite database: {e}")
        return False

def main():
    """Main migration function"""
    print("=" * 60)
    print("🚀 ChatCode: SQLite to PostgreSQL Migration")
    print("=" * 60)
    print()
    
    # Step 1: Backup SQLite database
    print("Step 1: Creating backup of SQLite database...")
    if not backup_sqlite():
        print("❌ Backup failed, but continuing with migration...")
    print()
    
    # Step 2: Extract data from SQLite
    print("Step 2: Extracting data from SQLite...")
    sqlite_data = get_sqlite_data()
    if not sqlite_data:
        print("⚠️  No data found in SQLite database or error occurred")
        return 1
    print()
    
    # Step 3: Set up PostgreSQL
    print("Step 3: Setting up PostgreSQL connection...")
    engine = setup_postgresql()
    if not engine:
        return 1
    print()
    
    # Step 4: Migrate data
    print("Step 4: Migrating data...")
    if not migrate_data(engine, sqlite_data):
        return 1
    print()
    
    # Step 5: Verify migration
    print("Step 5: Verifying migration...")
    if not verify_migration(engine, len(sqlite_data)):
        return 1
    print()
    
    print("🎉 Migration completed successfully!")
    print()
    print("Next steps:")
    print("1. Test your application with PostgreSQL")
    print("2. Update your production environment variables")
    print("3. Deploy with PostgreSQL configuration")
    print()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
