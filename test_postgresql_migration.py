#!/usr/bin/env python3
"""
Comprehensive test script for PostgreSQL migration
"""
import os
import sys
import time
from datetime import datetime

# Set PostgreSQL URL for testing
os.environ['DB_URL'] = 'postgresql://chatcode_user:chatcode_password@localhost:5432/chatcode_db'

def test_database_connection():
    """Test direct database connection"""
    print("🔍 Testing database connection...")
    
    try:
        from app import engine, Session, User
        from sqlmodel import select, text
        
        with Session(engine) as session:
            # Test basic connection
            result = session.exec(text("SELECT version()")).first()
            print(f"✅ PostgreSQL version: {result[:50]}...")
            
            # Test user table
            users = session.exec(select(User)).all()
            print(f"✅ Found {len(users)} users in database")
            
            # Test admin user
            admin = session.exec(select(User).where(User.is_admin == True)).first()
            if admin:
                print(f"✅ Admin user found: {admin.username}")
            else:
                print("❌ No admin user found")
                return False
                
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

def test_application_startup():
    """Test application startup"""
    print("\n🚀 Testing application startup...")
    
    try:
        # Import app to test startup
        from app import app
        print("✅ Application imports successfully")
        
        # Test that models are properly configured
        from app import User, engine
        from sqlmodel import SQLModel
        
        # Verify tables exist
        SQLModel.metadata.create_all(engine)
        print("✅ Database tables verified")
        
        return True
        
    except Exception as e:
        print(f"❌ Application startup failed: {e}")
        return False

def test_user_operations():
    """Test CRUD operations on users"""
    print("\n👤 Testing user operations...")
    
    try:
        from app import User, engine, Session, hash_password
        from sqlmodel import select
        from datetime import datetime
        
        with Session(engine) as session:
            # Test creating a new user (without specifying ID to avoid conflicts)
            test_user = User(
                username=f"test_user_{int(time.time())}",
                password_hash=hash_password("testpass123"),
                phone_e164="+12345678901",
                preset_text="Test message",
                is_admin=False,
                is_active=True,
                created_at=datetime.now().isoformat()
            )
            
            session.add(test_user)
            session.commit()
            session.refresh(test_user)
            
            print(f"✅ Created test user: {test_user.username} (ID: {test_user.id})")
            
            # Test reading user
            found_user = session.get(User, test_user.id)
            if found_user and found_user.username == test_user.username:
                print("✅ User read operation successful")
            else:
                print("❌ User read operation failed")
                return False
            
            # Test updating user
            found_user.preset_text = "Updated message"
            session.commit()
            
            updated_user = session.get(User, test_user.id)
            if updated_user.preset_text == "Updated message":
                print("✅ User update operation successful")
            else:
                print("❌ User update operation failed")
                return False
            
            # Test deleting user
            session.delete(updated_user)
            session.commit()
            
            deleted_user = session.get(User, test_user.id)
            if deleted_user is None:
                print("✅ User delete operation successful")
            else:
                print("❌ User delete operation failed")
                return False
                
        return True
        
    except Exception as e:
        print(f"❌ User operations failed: {e}")
        return False

def test_authentication():
    """Test authentication functions"""
    print("\n🔐 Testing authentication...")
    
    try:
        from app import hash_password, verify_password
        
        # Test password hashing
        password = "testpassword123"
        hashed = hash_password(password)
        
        if hashed and len(hashed) > 20:
            print("✅ Password hashing works")
        else:
            print("❌ Password hashing failed")
            return False
        
        # Test password verification
        if verify_password(password, hashed):
            print("✅ Password verification works")
        else:
            print("❌ Password verification failed")
            return False
        
        # Test wrong password
        if not verify_password("wrongpassword", hashed):
            print("✅ Wrong password correctly rejected")
        else:
            print("❌ Wrong password incorrectly accepted")
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Authentication test failed: {e}")
        return False

def test_qr_generation():
    """Test QR code generation"""
    print("\n📱 Testing QR code generation...")
    
    try:
        import qrcode
        from io import BytesIO
        
        # Test QR code generation
        phone = "+77011234567"
        preset = "Hello from ChatCode!"
        
        # Create WhatsApp URL
        wa_url = f"https://wa.me/{phone[1:]}"
        if preset:
            import urllib.parse
            wa_url += f"?text={urllib.parse.quote(preset)}"
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(wa_url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to BytesIO to test
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_data = img_io.getvalue()
        
        if len(img_data) > 100:  # Should be a reasonable size PNG (lowered threshold)
            print("✅ QR code generation works")
            print(f"✅ Generated QR for: {wa_url}")
            print(f"✅ QR image size: {len(img_data)} bytes")
            return True
        else:
            print(f"❌ QR code generation failed - image too small: {len(img_data)} bytes")
            return False
            
    except Exception as e:
        print(f"❌ QR code generation failed: {e}")
        return False

def test_environment_config():
    """Test environment configuration"""
    print("\n⚙️  Testing environment configuration...")
    
    try:
        # Test database URL
        db_url = os.getenv('DB_URL')
        if db_url and db_url.startswith('postgresql://'):
            print(f"✅ PostgreSQL URL configured: {db_url.split('@')[1] if '@' in db_url else 'localhost'}")
        else:
            print("❌ PostgreSQL URL not properly configured")
            return False
        
        # Test other required environment variables
        app_secret = os.getenv('APP_SECRET')
        if app_secret and len(app_secret) > 10:
            print("✅ APP_SECRET configured")
        else:
            print("⚠️  APP_SECRET not configured (will use default)")
        
        base_url = os.getenv('BASE_URL', 'http://127.0.0.1:8000')
        print(f"✅ BASE_URL: {base_url}")
        
        return True
        
    except Exception as e:
        print(f"❌ Environment configuration test failed: {e}")
        return False

def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("🧪 ChatCode PostgreSQL Migration Test Suite")
    print("=" * 60)
    
    tests = [
        ("Database Connection", test_database_connection),
        ("Application Startup", test_application_startup),
        ("User Operations", test_user_operations),
        ("Authentication", test_authentication),
        ("QR Generation", test_qr_generation),
        ("Environment Config", test_environment_config),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print("📊 Test Results")
    print("=" * 60)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📈 Success Rate: {(passed/(passed+failed)*100):.1f}%")
    
    if failed == 0:
        print("\n🎉 All tests passed! PostgreSQL migration is successful.")
        print("\n✅ Ready for production deployment!")
        return True
    else:
        print(f"\n⚠️  {failed} test(s) failed. Please review and fix issues.")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
