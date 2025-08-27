#!/usr/bin/env python3
"""
Test script for social authentication functionality
"""
import os
import sys
import time
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_app_startup():
    """Test that the app starts without errors"""
    print("Testing app startup...")
    try:
        # Import the app to check for any import errors
        from app import app, User, engine
        from sqlmodel import Session, select
        
        print("✓ App imports successfully")
        
        # Test database connection
        with Session(engine) as s:
            users = s.exec(select(User)).all()
            print(f"✓ Database connection works, found {len(users)} users")
        
        return True
    except Exception as e:
        print(f"✗ App startup failed: {e}")
        return False

def test_oauth_config():
    """Test OAuth configuration"""
    print("\nTesting OAuth configuration...")
    
    # Check environment variables
    google_configured = bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
    github_configured = bool(os.getenv("GITHUB_CLIENT_ID") and os.getenv("GITHUB_CLIENT_SECRET"))
    
    print(f"Google OAuth configured: {'✓' if google_configured else '✗'}")
    print(f"GitHub OAuth configured: {'✓' if github_configured else '✗'}")
    
    if not google_configured and not github_configured:
        print("⚠ No OAuth providers configured. Social login will not work.")
        print("  Set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET or GITHUB_CLIENT_ID/GITHUB_CLIENT_SECRET")
    
    return google_configured or github_configured

def test_routes_exist():
    """Test that social auth routes are properly defined"""
    print("\nTesting route definitions...")
    
    try:
        from app import app
        
        # Get all routes
        routes = []
        for route in app.routes:
            if hasattr(route, 'path'):
                routes.append(route.path)
        
        # Check for social auth routes
        auth_routes = [r for r in routes if '/auth/' in r]
        
        expected_routes = ['/auth/{provider}', '/auth/{provider}/callback']
        
        for expected in expected_routes:
            if expected in auth_routes:
                print(f"✓ Route {expected} exists")
            else:
                print(f"✗ Route {expected} missing")
        
        return len(auth_routes) >= 2
    except Exception as e:
        print(f"✗ Route testing failed: {e}")
        return False

def test_user_model():
    """Test that User model has social auth fields"""
    print("\nTesting User model...")
    
    try:
        from app import User
        
        # Check for social auth fields
        social_fields = ['email', 'full_name', 'profile_picture', 'social_provider', 'social_id', 'social_data']
        
        # Create a dummy user instance to check fields
        user = User(username="test", password_hash="test")
        
        for field in social_fields:
            if hasattr(user, field):
                print(f"✓ Field {field} exists")
            else:
                print(f"✗ Field {field} missing")
        
        return all(hasattr(user, field) for field in social_fields)
    except Exception as e:
        print(f"✗ User model testing failed: {e}")
        return False

def test_helper_functions():
    """Test helper functions for OAuth"""
    print("\nTesting helper functions...")
    
    try:
        from app import validate_oauth_provider, sanitize_user_input, create_oauth_state
        
        # Test provider validation
        assert validate_oauth_provider('google') in [True, False]  # Depends on config
        assert validate_oauth_provider('invalid') == False
        print("✓ validate_oauth_provider works")
        
        # Test input sanitization
        test_input = {'id': '123', 'name': 'Test User', 'email': 'test@example.com'}
        sanitized = sanitize_user_input(test_input)
        assert 'id' in sanitized
        print("✓ sanitize_user_input works")
        
        # Test state generation
        state = create_oauth_state()
        assert len(state) > 10
        print("✓ create_oauth_state works")
        
        return True
    except Exception as e:
        print(f"✗ Helper function testing failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=== Social Authentication Test Suite ===\n")
    
    tests = [
        test_app_startup,
        test_oauth_config,
        test_routes_exist,
        test_user_model,
        test_helper_functions
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    print(f"\n=== Test Results ===")
    print(f"Passed: {sum(results)}/{len(results)}")
    
    if all(results):
        print("🎉 All tests passed!")
        return 0
    else:
        print("❌ Some tests failed. Check the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
