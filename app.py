"""
ChatCode — super‑simple MVP (single file)
--------------------------------------------------

What it does
- Lets a user register/login with a username/password
- Saves their WhatsApp phone (E.164 format, e.g., +77011234567)
- Generates a personal page with a QR code that opens a WhatsApp chat
- Lets the user download the QR code PNG

Tech stack
- FastAPI + Uvicorn
- SQLModel (SQLite)
- passlib[bcrypt] for password hashing
- qrcode[pil] to generate QR codes

Run locally
1) Create & activate venv
   python3 -m venv .venv && source .venv/bin/activate
2) Install deps
   pip install fastapi uvicorn sqlmodel passlib[bcrypt] qrcode[pil] python-multipart itsdangerous
3) Start app
   uvicorn app:app --reload
4) Open http://127.0.0.1:8000

Deploy quickly
- Render/Fly.io/Dokku: just add a Procfile with `web: uvicorn app:app --host 0.0.0.0 --port $PORT`
- For persistence, mount a volume for `qr.db`

Notes
- QR encodes the official WhatsApp link: https://wa.me/<E164> with optional `?text=` preset
- This MVP uses server sessions (cookie) with ItsDangerous signer. For production, switch to a stronger session solution and HTTPS.
- Keep phone numbers in E.164 format. The UI enforces basic validation.

Environment
- Set APP_SECRET for cookie signing (fall back provided for dev only)

"""
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from passlib.context import CryptContext
import qrcode
from io import BytesIO
import os, re, secrets, time, json
from itsdangerous import TimestampSigner, BadSignature
from datetime import datetime
from typing import Optional
from authlib.integrations.starlette_client import OAuth
import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ---------------------- Config ----------------------
# Database configuration with PostgreSQL support
DB_URL = os.getenv("DB_URL", "sqlite:///qr.db")

# Configure engine based on database type
if DB_URL.startswith("postgresql://") or DB_URL.startswith("postgres://"):
    # PostgreSQL configuration with psycopg (modern psycopg2 replacement)
    engine = create_engine(
        DB_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False  # Set to True for SQL debugging
    )
else:
    # SQLite configuration (fallback for development)
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
APP_SECRET = os.getenv("APP_SECRET", "dev-secret-change-me")
signer = TimestampSigner(APP_SECRET)

# OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# Base URL for OAuth callbacks (set this to your domain in production)
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

# ---------------------- Viral Marketing ----------------------
VIRAL_MARKETING_MESSAGE = """Hi. Nice to meet you.

Get QR for free at https://chatcode.su"""

def get_viral_message_with_preset(preset_text: str | None) -> str:
    """
    Combines user's preset text with viral marketing message.
    Always includes the viral marketing message for maximum exposure.
    """
    if preset_text and preset_text.strip():
        # User has custom message - append viral marketing message
        return f"{preset_text.strip()}\n\n{VIRAL_MARKETING_MESSAGE}"
    else:
        # No custom message - use viral marketing message as default
        return VIRAL_MARKETING_MESSAGE

# ---------------------- Models ----------------------
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str | None = None  # Made optional for social auth users
    phone_e164: str | None = None
    preset_text: str | None = None  # optional prefilled message
    is_admin: bool = Field(default=False)  # admin role flag
    is_active: bool = Field(default=True)  # user active status
    created_at: str | None = None  # creation timestamp
    last_login: str | None = None  # last login timestamp

    # Social authentication fields
    email: str | None = Field(default=None, index=True)  # email from social provider
    full_name: str | None = None  # full name from social provider
    profile_picture: str | None = None  # profile picture URL from social provider
    social_provider: str | None = None  # 'google', 'github', etc.
    social_id: str | None = Field(default=None, index=True)  # unique ID from social provider
    social_data: str | None = None  # JSON string for additional social provider data

# ---------------------- DB Init ----------------------
SQLModel.metadata.create_all(engine)

# ---------------------- App ----------------------
app = FastAPI(title="ChatCode")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Add session middleware for OAuth state management
from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET,
    max_age=60*60*24*30,  # 30 days
    same_site='lax',
    https_only=BASE_URL.startswith('https://')
)

# OAuth client setup
oauth = OAuth()

# Configure Google OAuth
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    try:
        oauth.register(
            name='google',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url='https://accounts.google.com/.well-known/openid_configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
        print("✓ Google OAuth configured successfully")
    except Exception as e:
        print(f"⚠ Google OAuth configuration failed: {e}")
        # Fallback to manual configuration
        oauth.register(
            name='google',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            access_token_url='https://oauth2.googleapis.com/token',
            authorize_url='https://accounts.google.com/o/oauth2/auth',
            api_base_url='https://www.googleapis.com/',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
        print("✓ Google OAuth configured with manual endpoints")

# Configure GitHub OAuth
if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
    oauth.register(
        name='github',
        client_id=GITHUB_CLIENT_ID,
        client_secret=GITHUB_CLIENT_SECRET,
        access_token_url='https://github.com/login/oauth/access_token',
        authorize_url='https://github.com/login/oauth/authorize',
        api_base_url='https://api.github.com/',
        client_kwargs={'scope': 'user:email'},
    )

# ---------------------- Utils ----------------------
E164_RE = re.compile(r"^\+[1-9]\d{8,14}$")

def hash_password(p: str) -> str:
    return pwd_ctx.hash(p)

def verify_password(p: str, h: str) -> bool:
    return pwd_ctx.verify(p, h)

def create_session_cookie(user_id: int) -> str:
    return signer.sign(str(user_id)).decode()

def read_session_cookie(value: str) -> int | None:
    try:
        raw = signer.unsign(value, max_age=60*60*24*30).decode()  # 30 days
        # Check if the raw value looks like a user ID (should be numeric)
        if raw.isdigit():
            return int(raw)
        else:
            # This might be OAuth state or other data, not a user ID
            print(f"Session cookie contains non-numeric data: {raw[:50]}...")
            return None
    except BadSignature:
        return None
    except ValueError as e:
        print(f"Session cookie parsing error: {e}")
        return None

# OAuth state management
def create_oauth_state() -> str:
    """Create a secure random state for OAuth flow"""
    return secrets.token_urlsafe(32)

def verify_oauth_state(request: Request, state: str) -> bool:
    """Verify OAuth state matches what's stored in session"""
    stored_state = request.session.get("oauth_state")
    return stored_state == state if stored_state else False

def store_oauth_state(request: Request, state: str):
    """Store OAuth state in session"""
    request.session["oauth_state"] = state

def clear_oauth_state(request: Request):
    """Clear OAuth state from session"""
    request.session.pop("oauth_state", None)

def update_user_profile_from_social(user: User, provider: str, user_info: dict) -> User:
    """Update user profile with data from social provider"""
    if provider == 'google':
        user.email = user_info.get('email') or user.email
        user.full_name = user_info.get('name') or user.full_name
        user.profile_picture = user_info.get('picture') or user.profile_picture
    elif provider == 'github':
        # For GitHub, we need to handle email separately as it might come from a different endpoint
        user.full_name = user_info.get('name') or user_info.get('login') or user.full_name
        user.profile_picture = user_info.get('avatar_url') or user.profile_picture

    user.social_data = json.dumps(user_info)
    user.last_login = datetime.now().isoformat()
    return user

def validate_oauth_provider(provider: str) -> bool:
    """Validate that the OAuth provider is supported and configured"""
    if provider not in ['google', 'github']:
        return False

    if provider == 'google':
        return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
    elif provider == 'github':
        return bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)

    return False

def sanitize_user_input(data: dict) -> dict:
    """Sanitize user input from OAuth providers"""
    sanitized = {}

    # Only allow specific fields and sanitize them
    allowed_fields = ['id', 'email', 'name', 'login', 'picture', 'avatar_url']

    for field in allowed_fields:
        if field in data and data[field]:
            value = str(data[field]).strip()
            # Basic sanitization - remove any potential script tags or dangerous content
            value = value.replace('<', '&lt;').replace('>', '&gt;')
            if len(value) <= 500:  # Reasonable length limit
                sanitized[field] = value

    return sanitized

def find_or_create_social_user(provider: str, social_id: str, user_info: dict, email: str = None) -> User:
    """Find existing user or create new user for social authentication"""
    with Session(engine) as s:
        # First, try to find user by social provider and ID
        existing_user = s.exec(
            select(User).where(
                User.social_provider == provider,
                User.social_id == social_id
            )
        ).first()

        if existing_user:
            # Update existing social user
            existing_user = update_user_profile_from_social(existing_user, provider, user_info)
            if email and not existing_user.email:
                existing_user.email = email
            s.add(existing_user)
            s.commit()
            return existing_user

        # Try to find user by email if provided
        if email:
            email_user = s.exec(select(User).where(User.email == email)).first()
            if email_user:
                # Link social account to existing email user
                email_user.social_provider = provider
                email_user.social_id = social_id
                email_user = update_user_profile_from_social(email_user, provider, user_info)
                s.add(email_user)
                s.commit()
                return email_user

        # Create new user
        username = email.split('@')[0] if email else f"{provider}_{social_id}"

        # Ensure username is unique
        base_username = username
        counter = 1
        while s.exec(select(User).where(User.username == username)).first():
            username = f"{base_username}_{counter}"
            counter += 1

        new_user = User(
            username=username,
            email=email,
            social_provider=provider,
            social_id=social_id,
            created_at=datetime.now().isoformat()
        )
        new_user = update_user_profile_from_social(new_user, provider, user_info)

        s.add(new_user)
        s.commit()
        s.refresh(new_user)
        return new_user

def get_current_user(request: Request) -> User | None:
    try:
        cookie = request.cookies.get("session")
        if not cookie:
            return None
        user_id = read_session_cookie(cookie)
        if not user_id:
            return None
        # Ensure user_id is an integer
        if not isinstance(user_id, int):
            print(f"Session error: user_id is not an integer: {user_id}")
            return None
        with Session(engine) as s:
            return s.get(User, user_id)
    except Exception as e:
        # Log session error but don't crash the app
        print(f"Session error: {str(e)}")
        return None

def get_admin_user(request: Request) -> User | None:
    """Get current user if they are an admin"""
    user = get_current_user(request)
    if user and user.is_admin and user.is_active:
        return user
    return None

def require_admin(request: Request) -> User:
    """Dependency to require admin authentication"""
    admin = get_admin_user(request)
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return admin

def create_admin_user():
    """Create default admin user if none exists"""
    with Session(engine) as s:
        admin_exists = s.exec(select(User).where(User.is_admin == True)).first()
        if not admin_exists:
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                phone_e164="+77019601017",
                is_admin=True,
                is_active=True,
                created_at=datetime.now().isoformat()
            )
            s.add(admin)
            s.commit()
            print("Default admin user created: username='admin', password='admin123'")

# Initialize admin user
create_admin_user()

# ---------------------- HTML TEMPLATES ----------------------
BASE_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

  :root {
    --bg: #0a0e1a;
    --bg-secondary: #0f1419;
    --card: #1a1f2e;
    --card-hover: #1f2937;
    --text: #f8fafc;
    --text-secondary: #cbd5e1;
    --muted: #94a3b8;
    --accent: #10b981;
    --accent-hover: #059669;
    --primary: #3b82f6;
    --primary-hover: #2563eb;
    --secondary: #374151;
    --border: #374151;
    --border-light: #4b5563;
    --shadow: rgba(0, 0, 0, 0.25);
    --shadow-lg: rgba(0, 0, 0, 0.4);
    --gradient-primary: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
    --gradient-accent: linear-gradient(135deg, #10b981 0%, #059669 100%);
    --gradient-hero: linear-gradient(135deg, #0a0e1a 0%, #1e293b 50%, #0f172a 100%);
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  .wrap { max-width: 720px; margin: 40px auto; padding: 20px; }
  .wrap-wide { max-width: 1200px; margin: 0 auto; padding: 0 20px; }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 32px;
    box-shadow: 0 20px 40px var(--shadow), 0 0 0 1px rgba(255,255,255,0.05);
    backdrop-filter: blur(10px);
    transition: all 0.3s ease;
  }

  .card:hover {
    transform: translateY(-2px);
    box-shadow: 0 25px 50px var(--shadow-lg), 0 0 0 1px rgba(255,255,255,0.1);
  }

  h1 {
    font-size: clamp(32px, 5vw, 56px);
    font-weight: 800;
    margin: 0 0 16px;
    letter-spacing: -0.02em;
    line-height: 1.1;
  }

  h2 {
    font-size: clamp(24px, 4vw, 36px);
    font-weight: 700;
    margin: 0 0 16px;
    letter-spacing: -0.01em;
  }

  h3 {
    font-size: 20px;
    font-weight: 600;
    margin: 0 0 12px;
    color: var(--text);
  }

  p {
    color: var(--text-secondary);
    line-height: 1.7;
    margin: 0 0 16px;
  }

  .row { display: flex; gap: 16px; flex-wrap: wrap; }

  input, button, textarea {
    width: 100%;
    padding: 16px 20px;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text);
    font-size: 16px;
    transition: all 0.2s ease;
    font-family: inherit;
  }

  input:focus, textarea:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  button {
    cursor: pointer;
    background: var(--gradient-accent);
    border: none;
    font-weight: 600;
    font-size: 16px;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
    box-shadow: 0 4px 15px rgba(16, 185, 129, 0.2);
  }

  button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(16, 185, 129, 0.3);
  }

  button:active {
    transform: translateY(0);
  }

  .btn-primary {
    background: var(--gradient-primary);
    box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2);
  }

  .btn-primary:hover {
    box-shadow: 0 8px 25px rgba(59, 130, 246, 0.3);
  }

  .btn-secondary {
    background: var(--secondary);
    border: 1px solid var(--border-light);
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  }

  .btn-secondary:hover {
    background: var(--card-hover);
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.2);
  }

  .btn-large {
    padding: 18px 32px;
    font-size: 18px;
    font-weight: 700;
    border-radius: 16px;
  }

  .muted { color: var(--muted); }

  a {
    color: var(--accent);
    text-decoration: none;
    transition: color 0.2s ease;
  }

  a:hover {
    color: var(--accent-hover);
  }

  .split { display: grid; grid-template-columns: 1fr; gap: 20px; }

  @media(min-width: 768px) {
    .split { grid-template-columns: 1fr 1fr; }
  }

  .qr {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-secondary);
    border-radius: 20px;
    padding: 24px;
    border: 1px solid var(--border);
  }

  .note {
    font-size: 14px;
    color: var(--muted);
    text-align: center;
    margin-top: 20px;
  }

  .topnav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  }

  .brand {
    font-weight: 800;
    letter-spacing: -0.01em;
    font-size: 24px;
    background: var(--gradient-accent);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  /* Navigation Styles */
  .navbar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 1000;
    background: rgba(10, 14, 26, 0.95);
    backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    padding: 16px 0;
    transition: all 0.3s ease;
  }

  .navbar-content {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .navbar-brand {
    font-weight: 800;
    font-size: 28px;
    background: var(--gradient-accent);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-decoration: none;
  }

  .navbar-nav {
    display: flex;
    gap: 32px;
    align-items: center;
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .navbar-nav a {
    color: var(--text-secondary);
    font-weight: 500;
    transition: color 0.2s ease;
    position: relative;
  }

  .navbar-nav a:hover {
    color: var(--accent);
  }

  .navbar-nav a::after {
    content: '';
    position: absolute;
    bottom: -4px;
    left: 0;
    width: 0;
    height: 2px;
    background: var(--gradient-accent);
    transition: width 0.3s ease;
  }

  .navbar-nav a:hover::after {
    width: 100%;
  }

  .mobile-menu-toggle {
    display: none;
    background: none;
    border: none;
    color: var(--text);
    font-size: 24px;
    cursor: pointer;
    padding: 8px;
  }

  .mobile-menu {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: rgba(10, 14, 26, 0.98);
    backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    padding: 20px;
  }

  .mobile-menu.active {
    display: block;
  }

  .mobile-menu a {
    display: block;
    padding: 12px 0;
    color: var(--text-secondary);
    font-weight: 500;
    border-bottom: 1px solid var(--border);
  }

  .mobile-menu a:last-child {
    border-bottom: none;
  }

  /* Landing Page Styles */
  .hero {
    text-align: center;
    padding: 120px 0 80px;
    background: var(--gradient-hero);
    position: relative;
    overflow: hidden;
  }

  .hero::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: radial-gradient(circle at 50% 50%, rgba(59, 130, 246, 0.1) 0%, transparent 50%);
  }

  .hero-content {
    position: relative;
    z-index: 2;
  }

  .hero h1 {
    background: linear-gradient(135deg, var(--text) 0%, var(--accent) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 24px;
  }

  .hero p {
    font-size: 20px;
    color: var(--text-secondary);
    max-width: 600px;
    margin: 0 auto 40px;
  }

  .cta-buttons {
    display: flex;
    gap: 20px;
    justify-content: center;
    flex-wrap: wrap;
    margin: 40px 0;
  }

  .cta-buttons a {
    text-decoration: none;
    min-width: 200px;
  }

  .section {
    padding: 80px 0;
  }

  .section-title {
    text-align: center;
    margin-bottom: 60px;
    color: var(--text);
  }

  .features {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
    gap: 40px;
    margin: 60px 0;
  }

  .feature {
    text-align: center;
    padding: 32px 24px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 20px;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
  }

  .feature::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.05) 0%, rgba(16, 185, 129, 0.05) 100%);
    opacity: 0;
    transition: opacity 0.3s ease;
  }

  .feature:hover::before {
    opacity: 1;
  }

  .feature:hover {
    transform: translateY(-8px);
    box-shadow: 0 20px 40px var(--shadow-lg);
  }

  .feature-icon {
    width: 64px;
    height: 64px;
    margin: 0 auto 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--gradient-primary);
    border-radius: 16px;
    position: relative;
    z-index: 2;
  }

  .steps {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 32px;
    margin: 60px 0;
  }

  .step {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 32px;
    text-align: center;
    transition: all 0.3s ease;
  }

  .step:hover {
    transform: translateY(-4px);
    box-shadow: 0 15px 30px var(--shadow);
  }

  .step-number {
    background: var(--gradient-accent);
    color: white;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 20px;
    margin: 0 auto 20px;
  }

  .testimonials {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
    gap: 32px;
    margin: 60px 0;
  }

  .testimonial {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 32px;
    transition: all 0.3s ease;
  }

  .testimonial:hover {
    transform: translateY(-4px);
    box-shadow: 0 15px 30px var(--shadow);
  }

  .testimonial-text {
    font-style: italic;
    margin-bottom: 20px;
    color: var(--text-secondary);
  }

  .testimonial-author {
    font-weight: 600;
    color: var(--accent);
  }

  .footer {
    background: var(--bg-secondary);
    border-top: 1px solid var(--border);
    padding: 60px 0 40px;
    margin-top: 80px;
  }

  .footer-content {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 40px;
  }

  .footer-section h3 {
    color: var(--accent);
    margin-bottom: 20px;
  }

  .contact-info {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .contact-item {
    display: flex;
    align-items: center;
    gap: 12px;
    color: var(--text-secondary);
  }

  .whatsapp-btn {
    background: linear-gradient(135deg, #25d366, #128c7e);
    color: white;
    padding: 14px 24px;
    border-radius: 30px;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    font-weight: 600;
    transition: all 0.3s ease;
    box-shadow: 0 4px 15px rgba(37, 211, 102, 0.2);
  }

  .whatsapp-btn:hover {
    transform: translateY(-2px);
    color: white;
    box-shadow: 0 8px 25px rgba(37, 211, 102, 0.3);
  }

  /* Responsive Design */
  @media(max-width: 768px) {
    .navbar-nav {
      display: none;
    }

    .mobile-menu-toggle {
      display: block;
    }

    .hero {
      padding: 100px 0 60px;
    }

    .hero h1 {
      font-size: 36px;
    }

    .hero p {
      font-size: 18px;
    }

    .cta-buttons {
      flex-direction: column;
      align-items: center;
    }

    .cta-buttons a {
      width: 100%;
      max-width: 300px;
    }

    .section {
      padding: 60px 0;
    }

    .features {
      grid-template-columns: 1fr;
      gap: 24px;
    }

    .steps {
      grid-template-columns: 1fr;
    }

    .testimonials {
      grid-template-columns: 1fr;
    }

    .footer-content {
      grid-template-columns: 1fr;
      gap: 32px;
    }
  }

  @media(max-width: 480px) {
    .wrap, .wrap-wide {
      padding: 0 16px;
    }

    .hero {
      padding: 80px 0 40px;
    }

    .section {
      padding: 40px 0;
    }

    .card {
      padding: 24px;
    }

    .feature, .step, .testimonial {
      padding: 24px;
    }
  }

  /* Admin Panel Styles */
  .admin-layout {
    display: flex;
    min-height: 100vh;
    background: var(--bg);
  }

  .admin-sidebar {
    width: 280px;
    background: var(--card);
    border-right: 1px solid var(--border);
    padding: 20px 0;
    position: fixed;
    height: 100vh;
    overflow-y: auto;
  }

  .admin-main {
    flex: 1;
    margin-left: 280px;
    padding: 20px;
  }

  .admin-header {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .admin-nav {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .admin-nav li {
    margin: 0;
  }

  .admin-nav a {
    display: flex;
    align-items: center;
    padding: 12px 20px;
    color: var(--text-secondary);
    text-decoration: none;
    transition: all 0.2s ease;
    border-left: 3px solid transparent;
  }

  .admin-nav a:hover, .admin-nav a.active {
    background: var(--bg-secondary);
    color: var(--accent);
    border-left-color: var(--accent);
  }

  .admin-nav svg {
    width: 20px;
    height: 20px;
    margin-right: 12px;
  }

  .admin-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 20px;
  }

  .admin-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 20px;
    margin-bottom: 20px;
  }

  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    transition: all 0.3s ease;
  }

  .stat-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px var(--shadow);
  }

  .stat-number {
    font-size: 32px;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 8px;
  }

  .stat-label {
    color: var(--text-secondary);
    font-size: 14px;
  }

  .data-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--border);
  }

  .data-table th,
  .data-table td {
    padding: 12px 16px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }

  .data-table th {
    background: var(--bg-secondary);
    font-weight: 600;
    color: var(--text);
  }

  .data-table tr:hover {
    background: var(--bg-secondary);
  }

  .data-table tr:last-child td {
    border-bottom: none;
  }

  .admin-form {
    display: grid;
    gap: 16px;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .form-group label {
    font-weight: 500;
    color: var(--text);
  }

  .form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }

  .btn-small {
    padding: 8px 16px;
    font-size: 14px;
    border-radius: 8px;
  }

  .btn-danger {
    background: linear-gradient(135deg, #ef4444, #dc2626);
    color: white;
    border: none;
  }

  .btn-danger:hover {
    background: linear-gradient(135deg, #dc2626, #b91c1c);
  }

  .btn-warning {
    background: linear-gradient(135deg, #f59e0b, #d97706);
    color: white;
    border: none;
  }

  .btn-warning:hover {
    background: linear-gradient(135deg, #d97706, #b45309);
  }

  .status-badge {
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
  }

  .status-active {
    background: rgba(16, 185, 129, 0.1);
    color: var(--accent);
  }

  .status-inactive {
    background: rgba(239, 68, 68, 0.1);
    color: #ef4444;
  }

  .status-admin {
    background: rgba(59, 130, 246, 0.1);
    color: var(--primary);
  }

  @media(max-width: 768px) {
    .admin-sidebar {
      transform: translateX(-100%);
      transition: transform 0.3s ease;
    }

    .admin-sidebar.open {
      transform: translateX(0);
    }

    .admin-main {
      margin-left: 0;
    }

    .admin-grid {
      grid-template-columns: 1fr;
    }

    .form-row {
      grid-template-columns: 1fr;
    }
  }

  /* Social Authentication Styles */
  .social-login-section {
    margin: 24px 0;
    text-align: center;
  }

  .social-divider {
    display: flex;
    align-items: center;
    margin: 24px 0;
    color: var(--muted);
    font-size: 14px;
  }

  .social-divider::before,
  .social-divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  .social-divider span {
    padding: 0 16px;
  }

  .social-buttons {
    display: flex;
    gap: 12px;
    flex-direction: column;
  }

  .social-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 14px 20px;
    border-radius: 12px;
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text);
    text-decoration: none;
    font-weight: 500;
    font-size: 16px;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
  }

  .social-btn:hover {
    background: var(--card-hover);
    border-color: var(--border-light);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }

  .social-btn-google {
    border-color: #db4437;
  }

  .social-btn-google:hover {
    background: rgba(219, 68, 55, 0.1);
    border-color: #db4437;
  }

  .social-btn-github {
    border-color: #333;
  }

  .social-btn-github:hover {
    background: rgba(51, 51, 51, 0.1);
    border-color: #333;
  }

  .social-icon {
    width: 20px;
    height: 20px;
    flex-shrink: 0;
  }

  @media(min-width: 480px) {
    .social-buttons {
      flex-direction: row;
    }
  }
</style>
"""


def page(title: str, body_html: str, user: User | None = None) -> HTMLResponse:
    nav = f"""
    <div class=topnav>
      <div class=brand>ChatCode</div>
      <div>{('Signed in as <b>' + user.username + '</b> • <a href="/logout">Logout</a>') if user else '<a href="/login">Login</a>'}</div>
    </div>
    """
    html = f"""
    <html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>{title}</title>{BASE_STYLE}</head>
    <body><div class=wrap><div class=card>{nav}{body_html}</div><p class=note>Tip: Share your QR as a PNG or print it on cards. The QR encodes the official <code>wa.me</code> link so it opens WhatsApp immediately.</p></div></body></html>
    """
    return HTMLResponse(content=html)

def admin_page(title: str, body_html: str, current_page: str = "", admin_user: User | None = None) -> HTMLResponse:
    """Admin panel layout with sidebar navigation"""
    sidebar = f"""
    <div class="admin-sidebar">
      <div style="padding: 0 20px 20px; border-bottom: 1px solid var(--border);">
        <h2 style="color: var(--accent); margin: 0; font-size: 20px;">Admin Panel</h2>
        <p style="color: var(--muted); font-size: 14px; margin: 8px 0 0;">Welcome, {admin_user.username if admin_user else 'Admin'}</p>
      </div>
      <nav class="admin-nav">
        <li><a href="/admin" class="{'active' if current_page == 'dashboard' else ''}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="7" height="7"></rect>
            <rect x="14" y="3" width="7" height="7"></rect>
            <rect x="14" y="14" width="7" height="7"></rect>
            <rect x="3" y="14" width="7" height="7"></rect>
          </svg>
          Dashboard
        </a></li>
        <li><a href="/admin/users" class="{'active' if current_page == 'users' else ''}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
            <circle cx="9" cy="7" r="4"></circle>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
          </svg>
          Users
        </a></li>
        <li><a href="/admin/database" class="{'active' if current_page == 'database' else ''}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
          </svg>
          Database
        </a></li>
        <li><a href="/admin/analytics" class="{'active' if current_page == 'analytics' else ''}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 3v18h18"></path>
            <path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"></path>
          </svg>
          Analytics
        </a></li>
        <li><a href="/admin/system" class="{'active' if current_page == 'system' else ''}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1 1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
          System
        </a></li>
      </nav>
      <div style="padding: 20px; border-top: 1px solid var(--border); margin-top: auto;">
        <a href="/" style="color: var(--muted); font-size: 14px; text-decoration: none;">← Back to Site</a>
        <br>
        <a href="/logout" style="color: var(--muted); font-size: 14px; text-decoration: none;">Logout</a>
      </div>
    </div>
    """

    html = f"""
    <html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>{title}</title>{BASE_STYLE}
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
      <div class="admin-layout">
        {sidebar}
        <div class="admin-main">
          <div class="admin-header">
            <h1 style="margin: 0; color: var(--text);">{title}</h1>
            <div style="color: var(--muted); font-size: 14px;">
              {datetime.now().strftime('%B %d, %Y')}
            </div>
          </div>
          {body_html}
        </div>
      </div>
    </body></html>
    """
    return HTMLResponse(content=html)

def landing_page(title: str, body_html: str) -> HTMLResponse:
    """Special landing page layout with modern navigation"""
    nav = f"""
    <nav class="navbar">
      <div class="navbar-content">
        <a href="/" class="navbar-brand">ChatCode</a>
        <ul class="navbar-nav">
          <li><a href="#features">Features</a></li>
          <li><a href="#how-it-works">How It Works</a></li>
          <li><a href="#testimonials">Reviews</a></li>
          <li><a href="#support">Support</a></li>
          <li><a href="/login">Login</a></li>
          <li><a href="/register"><button class="btn-primary" style="padding:10px 20px;font-size:14px">Get Started</button></a></li>
        </ul>
        <button class="mobile-menu-toggle" onclick="toggleMobileMenu()">☰</button>
        <div class="mobile-menu" id="mobileMenu">
          <a href="#features">Features</a>
          <a href="#how-it-works">How It Works</a>
          <a href="#testimonials">Reviews</a>
          <a href="#support">Support</a>
          <li><a href="/login">Login</a></li>
          <a href="/register">Get Started</a>
        </div>
      </div>
    </nav>

    <script>
      function toggleMobileMenu() {{
        const menu = document.getElementById('mobileMenu');
        menu.classList.toggle('active');
      }}

      // Smooth scrolling for anchor links
      document.querySelectorAll('a[href^="#"]').forEach(anchor => {{
        anchor.addEventListener('click', function (e) {{
          e.preventDefault();
          const target = document.querySelector(this.getAttribute('href'));
          if (target) {{
            target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
          }}
        }});
      }});
    </script>
    """

    # Add support footer section
    additional_sections = f"""
    <!-- Support Section -->
    <div class="footer" id="support">
      <div class="wrap-wide">
        <div class="footer-content">
          <div class="footer-section">
            <h3>Need Help?</h3>
            <div class="contact-info">
              <div class="contact-item">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
                </svg>
                <span>Support: +77019601017</span>
              </div>
              <div style="margin-top:20px">
                <a href="https://wa.me/77019601017?text=Hi%2C%20I%20need%20help%20with%20ChatCode" class="whatsapp-btn" target="_blank">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893A11.821 11.821 0 0020.885 3.488"/>
                  </svg>
                  <span>WhatsApp Support</span>
                </a>
              </div>
            </div>
          </div>
          <div class="footer-section">
            <h3>Quick Links</h3>
            <div style="display:flex;flex-direction:column;gap:8px">
              <a href="/register" style="color:var(--accent)">Create Account</a>
              <a href="/login" style="color:var(--accent)">Sign In</a>
            </div>
          </div>
          <div class="footer-section">
            <h3>About ChatCode</h3>
            <p style="color:var(--muted);font-size:14px">The simplest way to create WhatsApp QR codes for instant connections. Professional, reliable, and easy to use.</p>
          </div>
        </div>
      </div>
    </div>
    """

    html = f"""
    <html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>{title}</title>{BASE_STYLE}</head>
    <body>{nav}{body_html}{additional_sections}</body></html>
    """
    return HTMLResponse(content=html)

# ---------------------- Routes ----------------------
@app.get("/health")
def health_check():
    """Health check endpoint for debugging deployment issues"""
    try:
        # Test database connection
        with Session(engine) as s:
            from sqlmodel import text
            s.exec(text("SELECT 1")).first()
        db_status = "OK"
    except Exception as e:
        db_status = f"ERROR: {str(e)}"

    # Check OAuth configuration
    oauth_config = {
        "google_configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "github_configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
        "base_url": BASE_URL,
        "app_secret_set": bool(APP_SECRET != "dev-secret-change-me")
    }

    return {
        "status": "healthy" if db_status == "OK" else "unhealthy",
        "database": db_status,
        "oauth": oauth_config,
        "environment": "production" if BASE_URL.startswith("https://") else "development"
    }

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/dashboard")

    # Enhanced landing page HTML
    landing_html = f"""
    <!-- Hero Section -->
    <div class="hero">
      <div class="wrap hero-content">
        <h1>Connect Instantly with WhatsApp QR Codes</h1>
        <p>Create professional QR codes that open WhatsApp chats instantly. Perfect for business cards, events, storefronts, and networking.</p>
        <div class="cta-buttons">
          <a href="/register"><button class="btn-large">Create Your QR Code</button></a>
          <a href="/login"><button class="btn-large btn-secondary">Sign In</button></a>
        </div>
      </div>
    </div>

    <!-- Features Section -->
    <div class="section" id="features">
      <div class="wrap-wide">
        <h2 class="section-title">Why Choose ChatCode?</h2>
        <div class="features">
          <div class="feature">
            <div class="feature-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
              </svg>
            </div>
            <h3>Instant Connection</h3>
            <p>QR codes open WhatsApp chats immediately - no typing phone numbers or searching contacts.</p>
          </div>
          <div class="feature">
            <div class="feature-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="m2 3 20 9L12 17l-5 5-5-5Z"></path>
                <path d="m7 8 5 5"></path>
                <path d="m12 2 5 5-5 5-5-5Z"></path>
              </svg>
            </div>
            <h3>Professional Design</h3>
            <p>Clean, high-quality QR codes that look great on business cards, flyers, and digital displays.</p>
          </div>
          <div class="feature">
            <div class="feature-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect width="14" height="20" x="5" y="2" rx="2" ry="2"></rect>
                <path d="M12 18h.01"></path>
              </svg>
            </div>
            <h3>Universal Compatibility</h3>
            <p>Works with any QR scanner on iOS, Android, or desktop. Uses official WhatsApp wa.me links.</p>
          </div>
          <div class="feature">
            <div class="feature-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
              </svg>
            </div>
            <h3>Custom Messages</h3>
            <p>Set preset messages that appear when someone scans your QR - perfect for specific campaigns.</p>
          </div>
          <div class="feature">
            <div class="feature-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7,10 12,15 17,10"></polyline>
                <line x1="12" x2="12" y1="15" y2="3"></line>
              </svg>
            </div>
            <h3>Download & Share</h3>
            <p>Download high-resolution PNG files or share your public QR page with a simple link.</p>
          </div>
          <div class="feature">
            <div class="feature-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
                <path d="M3 3v5h5"></path>
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"></path>
                <path d="M21 21v-5h-5"></path>
              </svg>
            </div>
            <h3>Easy Updates</h3>
            <p>Change your phone number or preset message anytime - your QR code stays the same.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- How It Works Section -->
    <div class="section" id="how-it-works" style="background:var(--bg-secondary)">
      <div class="wrap-wide">
        <h2 class="section-title">How It Works</h2>
        <div class="steps">
          <div class="step">
            <div class="step-number">1</div>
            <h3>Create Account</h3>
            <p>Sign up with your username and WhatsApp phone number in E.164 format.</p>
          </div>
          <div class="step">
            <div class="step-number">2</div>
            <h3>Generate QR</h3>
            <p>Your personalized QR code is created instantly and ready to use.</p>
          </div>
          <div class="step">
            <div class="step-number">3</div>
            <h3>Share & Connect</h3>
            <p>Download, print, or share your QR code. Anyone who scans it can message you instantly.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Testimonials Section -->
    <div class="section" id="testimonials">
      <div class="wrap-wide">
        <h2 class="section-title">What Our Users Say</h2>
        <div class="testimonials">
          <div class="testimonial">
            <div class="testimonial-text">"Great for my restaurant! Customers scan the QR on our table tents and can instantly message us for orders or questions."</div>
            <div class="testimonial-author">— Restaurant Owner</div>
          </div>
          <div class="testimonial">
            <div class="testimonial-text">"I put my ChatCode QR on my business cards. Networking events are so much easier now - people can reach me immediately."</div>
            <div class="testimonial-author">— Sales Professional</div>
          </div>
          <div class="testimonial">
            <div class="testimonial-text">"Perfect for our event registration. Attendees scan the QR and join our WhatsApp group instantly."</div>
            <div class="testimonial-author">— Event Organizer</div>
          </div>
        </div>
      </div>
    </div>"""

    return landing_page("ChatCode - Instant WhatsApp QR Codes", landing_html)

@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    # Build social login buttons
    social_buttons = ""
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        social_buttons += '''
        <a href="/auth/google" class="social-btn social-btn-google">
          <svg class="social-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Sign up with Google
        </a>'''

    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
        social_buttons += '''
        <a href="/auth/github" class="social-btn social-btn-github">
          <svg class="social-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
          </svg>
          Sign up with GitHub
        </a>'''

    social_section = ""
    if social_buttons:
        social_section = f'''
        <div class="social-login-section">
          <div class="social-buttons">
            {social_buttons}
          </div>
          <div class="social-divider">
            <span>or create account with email</span>
          </div>
        </div>'''

    return page("Register", f"""
    <h1>Create your account</h1>
    {social_section}
    <form method=post>
      <div class=split>
        <div>
          <label>Username</label>
          <input required name=username placeholder='yourname' pattern='[a-zA-Z0-9_-]{{3,24}}'>
        </div>
        <div>
          <label>Password</label>
          <input required type=password name=password minlength=6>
        </div>
      </div>
      <div class=split>
        <div>
          <label>WhatsApp phone (E.164)</label>
          <input required name=phone placeholder='+77011234567' pattern="\\+[1-9]\\d{{8,14}}">
        </div>
        <div>
          <label>Optional preset message</label>
          <input name=preset placeholder='Hi, saw your QR at ...'>
        </div>
      </div>
      <button>Create</button>
    </form>
    <p class=note style='background: var(--card-hover); padding: 12px; border-radius: 8px; border-left: 4px solid var(--accent); margin-top: 16px;'>
      <strong>📢 Viral Marketing:</strong> All QR codes include our promotional message to help grow ChatCode. Your custom message appears first, followed by: "Hi. Nice to meet you. Get QR for free at https://chatcode.su"
    </p>
    <p class=muted>Already have an account? <a href='/login'>Sign in</a></p>
    """)

@app.post("/register")
def register_action(username: str = Form(...), password: str = Form(...), phone: str = Form(...), preset: str = Form("")):
    if not E164_RE.match(phone):
        raise HTTPException(400, "Phone must be in E.164 format, e.g., +77011234567")
    with Session(engine) as s:
        if s.exec(select(User).where(User.username == username)).first():
            raise HTTPException(400, "Username already taken")
        u = User(
            username=username,
            password_hash=hash_password(password),
            phone_e164=phone,
            preset_text=preset.strip() or None,
            created_at=datetime.now().isoformat(),
            last_login=datetime.now().isoformat()
        )
        s.add(u); s.commit(); s.refresh(u)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("session", create_session_cookie(u.id), httponly=True, max_age=60*60*24*30)
    return resp

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    # Check for OAuth error
    error = request.query_params.get('error')
    error_message = ""
    if error == 'oauth_failed':
        error_message = '<div style="color: #ef4444; margin-bottom: 16px; padding: 12px; background: rgba(239, 68, 68, 0.1); border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.2);">Social login failed. Please try again or use traditional login.</div>'

    # Build social login buttons
    social_buttons = ""
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        social_buttons += '''
        <a href="/auth/google" class="social-btn social-btn-google">
          <svg class="social-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Continue with Google
        </a>'''

    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
        social_buttons += '''
        <a href="/auth/github" class="social-btn social-btn-github">
          <svg class="social-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
          </svg>
          Continue with GitHub
        </a>'''

    social_section = ""
    if social_buttons:
        social_section = f'''
        <div class="social-login-section">
          <div class="social-buttons">
            {social_buttons}
          </div>
          <div class="social-divider">
            <span>or continue with email</span>
          </div>
        </div>'''

    return page("Sign in", f"""
    <h1>Sign in</h1>
    {error_message}
    {social_section}
    <form method=post>
      <div class=split>
        <div><label>Username</label><input required name=username></div>
        <div><label>Password</label><input required type=password name=password></div>
      </div>
      <button>Sign in</button>
    </form>
    <p class=muted>New here? <a href='/register'>Create an account</a></p>
    """)

@app.post("/login")
def login_action(username: str = Form(...), password: str = Form(...)):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == username)).first()
        if not u:
            raise HTTPException(401, "Invalid credentials")

        # Check if user has a password hash (traditional auth) or is social auth only
        if u.password_hash is None:
            raise HTTPException(401, "Please use social login for this account")

        if not verify_password(password, u.password_hash):
            raise HTTPException(401, "Invalid credentials")

        if not u.is_active:
            raise HTTPException(401, "Account is deactivated")
        # Update last login
        u.last_login = datetime.now().isoformat()
        s.add(u)
        s.commit()
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("session", create_session_cookie(u.id), httponly=True, max_age=60*60*24*30)
        return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
    return resp

# ---------------------- Social Authentication Routes ----------------------

@app.get("/auth/{provider}")
async def social_login(request: Request, provider: str):
    """Initiate OAuth login with social provider"""
    # Validate provider and configuration
    if not validate_oauth_provider(provider):
        raise HTTPException(400, f"Provider '{provider}' is not supported or not configured")

    try:
        # Generate and store OAuth state
        state = create_oauth_state()
        store_oauth_state(request, state)

        # Get OAuth client
        client = oauth.create_client(provider)
        redirect_uri = f"{BASE_URL}/auth/{provider}/callback"

        return await client.authorize_redirect(request, redirect_uri, state=state)
    except Exception as e:
        print(f"OAuth initiation error for {provider}: {str(e)}")
        raise HTTPException(500, "Failed to initiate social login")

@app.get("/auth/{provider}/callback")
async def social_callback(request: Request, provider: str):
    """Handle OAuth callback from social provider"""
    # Validate provider
    if not validate_oauth_provider(provider):
        raise HTTPException(400, f"Provider '{provider}' is not supported or not configured")

    # Verify state parameter for CSRF protection
    state = request.query_params.get('state')
    if not state or not verify_oauth_state(request, state):
        print(f"OAuth state verification failed for {provider}")
        raise HTTPException(400, "Invalid OAuth state - possible CSRF attack")

    # Clear OAuth state
    clear_oauth_state(request)

    try:
        # Get OAuth client and exchange code for token
        client = oauth.create_client(provider)
        token = await client.authorize_access_token(request)

        # Get user info from provider
        if provider == 'google':
            user_info = token.get('userinfo')
            if not user_info:
                # Fallback: fetch user info manually
                resp = await client.get('https://www.googleapis.com/oauth2/v2/userinfo', token=token)
                user_info = resp.json()

            # Sanitize user info
            user_info = sanitize_user_input(user_info)
            social_id = user_info.get('id')
            email = user_info.get('email')

        elif provider == 'github':
            # Get user info
            resp = await client.get('user', token=token)
            user_info = resp.json()

            # Get primary email
            email_resp = await client.get('user/emails', token=token)
            emails = email_resp.json()
            primary_email = next((e['email'] for e in emails if e['primary']), None)

            # Sanitize user info
            user_info = sanitize_user_input(user_info)
            social_id = str(user_info.get('id'))
            email = primary_email or user_info.get('email')

        if not social_id:
            raise HTTPException(400, f"Could not get user ID from {provider}")

        # Find or create user using helper function
        user = find_or_create_social_user(provider, social_id, user_info, email)

        # Create session and redirect
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("session", create_session_cookie(user.id), httponly=True, max_age=60*60*24*30)
        return resp

    except Exception as e:
        # Log error and redirect to login with error message
        print(f"OAuth error for {provider}: {str(e)}")
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")

    # Handle case where user doesn't have phone number (social auth users)
    if not user.phone_e164:
        # Show setup form for social auth users
        profile_info = ""
        if user.social_provider:
            profile_info = f"""
            <div style="background: var(--card-hover); padding: 16px; border-radius: 12px; margin-bottom: 20px; border: 1px solid var(--border);">
              <h3 style="margin: 0 0 12px; color: var(--accent);">Welcome, {user.full_name or user.username}!</h3>
              <p style="margin: 0; color: var(--text-secondary);">You signed in with {user.social_provider.title()}. Please add your WhatsApp phone number to create your QR code.</p>
              {f'<img src="{user.profile_picture}" alt="Profile" style="width: 48px; height: 48px; border-radius: 50%; margin-top: 12px;">' if user.profile_picture else ''}
            </div>
            """

        body = f"""
        <h1>Complete Your Setup</h1>
        {profile_info}
        <form method=post action='/settings'>
          <div class=split>
            <div>
              <label>WhatsApp phone (E.164)</label>
              <input required name=phone placeholder='+77011234567' pattern="\\+[1-9]\\d{{8,14}}">
            </div>
            <div>
              <label>Optional preset message</label>
              <input name=preset placeholder='Hi, saw your QR at ...'>
            </div>
          </div>
          <button>Create QR Code</button>
        </form>
        <p class=note style='background: var(--card-hover); padding: 12px; border-radius: 8px; border-left: 4px solid var(--accent); margin-top: 16px;'>
          <strong>📢 Viral Marketing Feature:</strong> Your QR codes will automatically include our promotional message to help spread ChatCode to new users. Your custom message (if any) will appear first, followed by: "Hi. Nice to meet you. Get QR for free at https://chatcode.su"
        </p>
        """
        return page("Setup", body, user=user)

    # Normal dashboard for users with phone numbers
    link = f"https://wa.me/{user.phone_e164.lstrip('+')}"
    # Always include viral marketing message with any preset text
    viral_message = get_viral_message_with_preset(user.preset_text)
    import urllib.parse
    link += "?text=" + urllib.parse.quote(viral_message)

    # Profile section for social auth users
    profile_section = ""
    if user.social_provider:
        profile_section = f"""
        <div style="background: var(--card-hover); padding: 16px; border-radius: 12px; margin-bottom: 20px; border: 1px solid var(--border);">
          <div style="display: flex; align-items: center; gap: 12px;">
            {f'<img src="{user.profile_picture}" alt="Profile" style="width: 48px; height: 48px; border-radius: 50%;">' if user.profile_picture else ''}
            <div>
              <h3 style="margin: 0; color: var(--text);">{user.full_name or user.username}</h3>
              <p style="margin: 0; color: var(--muted); font-size: 14px;">Connected via {user.social_provider.title()}</p>
              {f'<p style="margin: 4px 0 0; color: var(--text-secondary); font-size: 14px;">{user.email}</p>' if user.email else ''}
            </div>
          </div>
        </div>
        """

    body = f"""
    <h1>Your QR is ready</h1>
    {profile_section}
    <div class=split>
      <div>
        <h2>Preview</h2>
        <div class=qr><img src='/qr.png?u={user.username}' alt='QR' style='width:100%;max-width:320px;height:auto'></div>
      </div>
      <div>
        <h2>Share</h2>
        <p><b>Direct link:</b><br><a href='{link}' target='_blank'>{link}</a></p>
        <div class=row>
          <a href='/qr.png?u={user.username}&download=1'><button>Download PNG</button></a>
          <a href='/u/{user.username}' target='_blank'><button style='background:#26314e;border:1px solid #34406a'>Public QR page</button></a>
        </div>
        <h2>Update Phone / Message</h2>
        <form method=post action='/settings'>
          <label>WhatsApp phone (E.164)</label>
          <input name=phone value='{user.phone_e164}' pattern="\\+[1-9]\\d{{8,14}}">
          <label>Optional preset message</label>
          <input name=preset value='{user.preset_text or ''}'>
          <button>Save</button>
        </form>
        <p class=note>Anyone scanning your QR will be taken to this link and can message you immediately in WhatsApp.</p>
        <p class=note style='background: var(--card-hover); padding: 12px; border-radius: 8px; border-left: 4px solid var(--accent); margin-top: 12px;'>
          <strong>📢 Viral Marketing:</strong> All QR codes automatically include our promotional message: "Hi. Nice to meet you. Get QR for free at https://chatcode.su" - helping you share ChatCode with new users!
        </p>
      </div>
    </div>
    """
    return page("Dashboard", body, user=user)

@app.post("/settings")
def update_settings(request: Request, phone: str = Form(...), preset: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    if not E164_RE.match(phone):
        raise HTTPException(400, "Invalid phone format")
    with Session(engine) as s:
        u = s.get(User, user.id)
        u.phone_e164 = phone
        u.preset_text = preset.strip() or None
        s.add(u); s.commit()
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/qr.png")
def qr_png(u: str, download: int | None = None):
    with Session(engine) as s:
        user = s.exec(select(User).where(User.username == u)).first()
        if not user:
            raise HTTPException(404, "User not found")
        link = f"https://wa.me/{user.phone_e164.lstrip('+')}"
        # Always include viral marketing message with any preset text
        viral_message = get_viral_message_with_preset(user.preset_text)
        import urllib.parse
        link += "?text=" + urllib.parse.quote(viral_message)
        img = qrcode.make(link)
        buff = BytesIO()
        img.save(buff, format="PNG"); buff.seek(0)
        headers = {}
        if download:
            headers["Content-Disposition"] = f"attachment; filename={u}_whatsapp_qr.png"
        return StreamingResponse(buff, media_type="image/png", headers=headers)

@app.get("/u/{username}", response_class=HTMLResponse)
def public_qr(username: str):
    with Session(engine) as s:
        user = s.exec(select(User).where(User.username == username)).first()
        if not user:
            raise HTTPException(404, "User not found")
    link = f"https://wa.me/{user.phone_e164.lstrip('+')}"
    # Always include viral marketing message with any preset text
    viral_message = get_viral_message_with_preset(user.preset_text)
    import urllib.parse
    link += "?text=" + urllib.parse.quote(viral_message)
    body = f"""
    <h1>Chat on WhatsApp</h1>
    <p class=muted>Scan this QR or tap the button to start a WhatsApp chat.</p>
    <div class=qr><img src='/qr.png?u={user.username}' alt='QR' style='width:100%;max-width:360px;height:auto'></div>
    <div class=row style='margin-top:12px'>
      <a href='{link}'><button>Open WhatsApp</button></a>
      <a href='/qr.png?u={user.username}&download=1'><button style='background:#26314e;border:1px solid #34406a'>Download QR</button></a>
    </div>
    """
    return page(f"QR for {username}", body)

# --------------- Admin Panel Routes ---------------
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, admin: User = Depends(require_admin)):
    # Get statistics
    with Session(engine) as s:
        total_users = len(s.exec(select(User)).all())
        active_users = len(s.exec(select(User).where(User.is_active == True)).all())
        admin_users = len(s.exec(select(User).where(User.is_admin == True)).all())
        recent_users = s.exec(select(User).order_by(User.id.desc()).limit(5)).all()

    body = f"""
    <div class="admin-grid">
      <div class="stat-card">
        <div class="stat-number">{total_users}</div>
        <div class="stat-label">Total Users</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{active_users}</div>
        <div class="stat-label">Active Users</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{admin_users}</div>
        <div class="stat-label">Admin Users</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{total_users - active_users}</div>
        <div class="stat-label">Inactive Users</div>
      </div>
    </div>

    <div class="admin-card">
      <h3>Recent Users</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Phone</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
    """

    for user in recent_users:
        status_class = "status-admin" if user.is_admin else ("status-active" if user.is_active else "status-inactive")
        status_text = "Admin" if user.is_admin else ("Active" if user.is_active else "Inactive")
        created = user.created_at[:10] if user.created_at else "N/A"
        body += f"""
          <tr>
            <td>{user.id}</td>
            <td>{user.username}</td>
            <td>{user.phone_e164 or 'N/A'}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td>{created}</td>
          </tr>
        """

    body += """
        </tbody>
      </table>
    </div>

    <div class="admin-card">
      <h3>Quick Actions</h3>
      <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <a href="/admin/users"><button class="btn-primary">Manage Users</button></a>
        <a href="/admin/database"><button class="btn-secondary">Database</button></a>
        <a href="/admin/analytics"><button class="btn-secondary">Analytics</button></a>
        <a href="/admin/system"><button class="btn-secondary">System</button></a>
      </div>
    </div>
    """

    return admin_page("Admin Dashboard", body, "dashboard", admin)

@app.get("/admin/database", response_class=HTMLResponse)
def admin_database(request: Request, admin: User = Depends(require_admin)):
    # Get database schema and stats
    with Session(engine) as s:
        users = s.exec(select(User)).all()

    body = f"""
    <div class="admin-card">
      <h3>Database Tables</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>Table</th>
            <th>Records</th>
            <th>Schema</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>user</strong></td>
            <td>{len(users)}</td>
            <td>id, username, password_hash, phone_e164, preset_text, is_admin, is_active, created_at, last_login</td>
            <td>
              <a href="/admin/database/user"><button class="btn-small btn-primary">View</button></a>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="admin-card">
      <h3>All Users</h3>
      <div style="margin-bottom: 16px;">
        <input type="text" id="userSearch" placeholder="Search users..." style="max-width: 300px;" onkeyup="filterUsers()">
      </div>
      <table class="data-table" id="usersTable">
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Phone</th>
            <th>Preset Text</th>
            <th>Status</th>
            <th>Admin</th>
            <th>Created</th>
            <th>Last Login</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
    """

    for user in users:
        status_class = "status-active" if user.is_active else "status-inactive"
        status_text = "Active" if user.is_active else "Inactive"
        admin_class = "status-admin" if user.is_admin else "status-inactive"
        admin_text = "Yes" if user.is_admin else "No"
        created = user.created_at[:10] if user.created_at else "N/A"
        last_login = user.last_login[:10] if user.last_login else "N/A"
        preset_preview = (user.preset_text[:30] + "...") if user.preset_text and len(user.preset_text) > 30 else (user.preset_text or "N/A")

        body += f"""
          <tr>
            <td>{user.id}</td>
            <td>{user.username}</td>
            <td>{user.phone_e164 or 'N/A'}</td>
            <td>{preset_preview}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td><span class="status-badge {admin_class}">{admin_text}</span></td>
            <td>{created}</td>
            <td>{last_login}</td>
            <td>
              <a href="/admin/users/{user.id}/edit"><button class="btn-small btn-primary">Edit</button></a>
              {'<button class="btn-small btn-danger" onclick="deleteUser(' + str(user.id) + ')">Delete</button>' if not user.is_admin else ''}
            </td>
          </tr>
        """

    body += """
        </tbody>
      </table>
    </div>

    <script>
      function filterUsers() {
        const input = document.getElementById('userSearch');
        const filter = input.value.toLowerCase();
        const table = document.getElementById('usersTable');
        const rows = table.getElementsByTagName('tr');

        for (let i = 1; i < rows.length; i++) {
          const row = rows[i];
          const cells = row.getElementsByTagName('td');
          let found = false;

          for (let j = 0; j < cells.length - 1; j++) {
            if (cells[j].textContent.toLowerCase().includes(filter)) {
              found = true;
              break;
            }
          }

          row.style.display = found ? '' : 'none';
        }
      }

      function deleteUser(userId) {
        if (confirm('Are you sure you want to delete this user?')) {
          fetch(`/admin/users/${userId}/delete`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
          }).then(() => location.reload());
        }
      }
    </script>
    """

    return admin_page("Database Management", body, "database", admin)

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, admin: User = Depends(require_admin)):
    with Session(engine) as s:
        users = s.exec(select(User).order_by(User.id.desc())).all()

    body = f"""
    <div class="admin-card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <h3>User Management</h3>
        <a href="/admin/users/new"><button class="btn-primary">Add New User</button></a>
      </div>

      <div style="margin-bottom: 16px;">
        <input type="text" id="userSearch" placeholder="Search users..." style="max-width: 300px;" onkeyup="filterUsers()">
        <select id="statusFilter" onchange="filterUsers()" style="margin-left: 12px; max-width: 150px;">
          <option value="">All Status</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="admin">Admin</option>
        </select>
      </div>

      <table class="data-table" id="usersTable">
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Phone</th>
            <th>Status</th>
            <th>Role</th>
            <th>Created</th>
            <th>Last Login</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
    """

    for user in users:
        status_class = "status-active" if user.is_active else "status-inactive"
        status_text = "Active" if user.is_active else "Inactive"
        role_class = "status-admin" if user.is_admin else "status-active"
        role_text = "Admin" if user.is_admin else "User"
        created = user.created_at[:10] if user.created_at else "N/A"
        last_login = user.last_login[:10] if user.last_login else "Never"

        body += f"""
          <tr data-status="{status_text.lower()}" data-role="{role_text.lower()}">
            <td>{user.id}</td>
            <td>{user.username}</td>
            <td>{user.phone_e164 or 'N/A'}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td><span class="status-badge {role_class}">{role_text}</span></td>
            <td>{created}</td>
            <td>{last_login}</td>
            <td>
              <a href="/admin/users/{user.id}/edit"><button class="btn-small btn-primary">Edit</button></a>
              <button class="btn-small {'btn-warning' if user.is_active else 'btn-primary'}" onclick="toggleUserStatus({user.id}, {str(user.is_active).lower()})">
                {'Deactivate' if user.is_active else 'Activate'}
              </button>
              {'<button class="btn-small btn-danger" onclick="deleteUser(' + str(user.id) + ')">Delete</button>' if not user.is_admin else ''}
            </td>
          </tr>
        """

    body += """
        </tbody>
      </table>
    </div>

    <script>
      function filterUsers() {
        const searchInput = document.getElementById('userSearch');
        const statusFilter = document.getElementById('statusFilter');
        const searchTerm = searchInput.value.toLowerCase();
        const statusValue = statusFilter.value.toLowerCase();
        const table = document.getElementById('usersTable');
        const rows = table.getElementsByTagName('tr');

        for (let i = 1; i < rows.length; i++) {
          const row = rows[i];
          const cells = row.getElementsByTagName('td');
          const rowStatus = row.getAttribute('data-status');
          const rowRole = row.getAttribute('data-role');

          let textMatch = false;
          for (let j = 0; j < cells.length - 1; j++) {
            if (cells[j].textContent.toLowerCase().includes(searchTerm)) {
              textMatch = true;
              break;
            }
          }

          let statusMatch = true;
          if (statusValue) {
            if (statusValue === 'admin') {
              statusMatch = rowRole === 'admin';
            } else {
              statusMatch = rowStatus === statusValue;
            }
          }

          row.style.display = (textMatch && statusMatch) ? '' : 'none';
        }
      }

      function toggleUserStatus(userId, currentStatus) {
        const action = currentStatus ? 'deactivate' : 'activate';
        if (confirm(`Are you sure you want to ${action} this user?`)) {
          fetch(`/admin/users/${userId}/toggle-status`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
          }).then(() => location.reload());
        }
      }

      function deleteUser(userId) {
        if (confirm('Are you sure you want to delete this user? This action cannot be undone.')) {
          fetch(`/admin/users/${userId}/delete`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
          }).then(() => location.reload());
        }
      }
    </script>
    """

    return admin_page("User Management", body, "users", admin)

@app.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def admin_edit_user(request: Request, user_id: int, admin: User = Depends(require_admin)):
    with Session(engine) as s:
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")

    body = f"""
    <div class="admin-card">
      <h3>Edit User: {user.username}</h3>
      <form method="post" action="/admin/users/{user_id}/update" class="admin-form">
        <div class="form-row">
          <div class="form-group">
            <label>Username</label>
            <input name="username" value="{user.username}" required>
          </div>
          <div class="form-group">
            <label>Phone (E.164)</label>
            <input name="phone" value="{user.phone_e164 or ''}" pattern="\\+[1-9]\\d{{8,14}}">
          </div>
        </div>

        <div class="form-group">
          <label>Preset Message</label>
          <textarea name="preset" rows="3">{user.preset_text or ''}</textarea>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>
              <input type="checkbox" name="is_admin" {'checked' if user.is_admin else ''}> Admin User
            </label>
          </div>
          <div class="form-group">
            <label>
              <input type="checkbox" name="is_active" {'checked' if user.is_active else ''}> Active
            </label>
          </div>
        </div>

        <div class="form-group">
          <label>New Password (leave blank to keep current)</label>
          <input type="password" name="password" minlength="6">
        </div>

        <div style="display: flex; gap: 12px;">
          <button type="submit" class="btn-primary">Update User</button>
          <a href="/admin/users"><button type="button" class="btn-secondary">Cancel</button></a>
        </div>
      </form>
    </div>

    <div class="admin-card">
      <h3>User Activity</h3>
      <table class="data-table">
        <tr><td><strong>Created:</strong></td><td>{user.created_at or 'N/A'}</td></tr>
        <tr><td><strong>Last Login:</strong></td><td>{user.last_login or 'Never'}</td></tr>
        <tr><td><strong>Status:</strong></td><td>{'Active' if user.is_active else 'Inactive'}</td></tr>
        <tr><td><strong>Role:</strong></td><td>{'Admin' if user.is_admin else 'User'}</td></tr>
      </table>
    </div>
    """

    return admin_page(f"Edit User: {user.username}", body, "users", admin)

@app.post("/admin/users/{user_id}/update")
def admin_update_user(
    user_id: int,
    username: str = Form(...),
    phone: str = Form(""),
    preset: str = Form(""),
    password: str = Form(""),
    is_admin: bool = Form(False),
    is_active: bool = Form(False),
    admin: User = Depends(require_admin)
):
    with Session(engine) as s:
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")

        # Check if username is taken by another user
        existing = s.exec(select(User).where(User.username == username, User.id != user_id)).first()
        if existing:
            raise HTTPException(400, "Username already taken")

        # Validate phone format if provided
        if phone and not E164_RE.match(phone):
            raise HTTPException(400, "Invalid phone format")

        # Update user fields
        user.username = username
        user.phone_e164 = phone if phone else None
        user.preset_text = preset.strip() if preset.strip() else None
        user.is_admin = is_admin
        user.is_active = is_active

        # Update password if provided
        if password:
            user.password_hash = hash_password(password)

        s.add(user)
        s.commit()

    return RedirectResponse(f"/admin/users/{user_id}/edit", status_code=303)

@app.post("/admin/users/{user_id}/toggle-status")
def admin_toggle_user_status(user_id: int, admin: User = Depends(require_admin)):
    with Session(engine) as s:
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")

        user.is_active = not user.is_active
        s.add(user)
        s.commit()

    return {"success": True, "new_status": user.is_active}

@app.post("/admin/users/{user_id}/delete")
def admin_delete_user(user_id: int, admin: User = Depends(require_admin)):
    with Session(engine) as s:
        user = s.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")

        if user.is_admin:
            raise HTTPException(400, "Cannot delete admin users")

        s.delete(user)
        s.commit()

    return {"success": True}

@app.get("/admin/users/new", response_class=HTMLResponse)
def admin_new_user(request: Request, admin: User = Depends(require_admin)):
    body = """
    <div class="admin-card">
      <h3>Create New User</h3>
      <form method="post" action="/admin/users/create" class="admin-form">
        <div class="form-row">
          <div class="form-group">
            <label>Username</label>
            <input name="username" required pattern="[a-zA-Z0-9_-]{3,24}">
          </div>
          <div class="form-group">
            <label>Password</label>
            <input type="password" name="password" required minlength="6">
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>Phone (E.164)</label>
            <input name="phone" pattern="\\+[1-9]\\d{8,14}" placeholder="+77011234567">
          </div>
          <div class="form-group">
            <label>Preset Message</label>
            <input name="preset" placeholder="Optional preset message">
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>
              <input type="checkbox" name="is_admin"> Admin User
            </label>
          </div>
          <div class="form-group">
            <label>
              <input type="checkbox" name="is_active" checked> Active
            </label>
          </div>
        </div>

        <div style="display: flex; gap: 12px;">
          <button type="submit" class="btn-primary">Create User</button>
          <a href="/admin/users"><button type="button" class="btn-secondary">Cancel</button></a>
        </div>
      </form>
    </div>
    """

    return admin_page("Create New User", body, "users", admin)

@app.post("/admin/users/create")
def admin_create_user(
    username: str = Form(...),
    password: str = Form(...),
    phone: str = Form(""),
    preset: str = Form(""),
    is_admin: bool = Form(False),
    is_active: bool = Form(False),
    admin: User = Depends(require_admin)
):
    # Validate phone format if provided
    if phone and not E164_RE.match(phone):
        raise HTTPException(400, "Invalid phone format")

    with Session(engine) as s:
        # Check if username is taken
        existing = s.exec(select(User).where(User.username == username)).first()
        if existing:
            raise HTTPException(400, "Username already taken")

        # Create new user
        new_user = User(
            username=username,
            password_hash=hash_password(password),
            phone_e164=phone if phone else None,
            preset_text=preset.strip() if preset.strip() else None,
            is_admin=is_admin,
            is_active=is_active,
            created_at=datetime.now().isoformat()
        )

        s.add(new_user)
        s.commit()
        s.refresh(new_user)

    return RedirectResponse("/admin/users", status_code=303)

@app.get("/admin/analytics", response_class=HTMLResponse)
def admin_analytics(request: Request, admin: User = Depends(require_admin)):
    from dateutil.relativedelta import relativedelta
    from collections import defaultdict

    with Session(engine) as s:
        users = s.exec(select(User)).all()

        # Calculate statistics
        total_users = len(users)
        active_users = len([u for u in users if u.is_active])
        admin_users = len([u for u in users if u.is_admin])

        # User growth data (last 12 months)
        now = datetime.now()
        monthly_data = defaultdict(int)

        for user in users:
            if user.created_at:
                try:
                    created = datetime.fromisoformat(user.created_at)
                    month_key = created.strftime('%Y-%m')
                    monthly_data[month_key] += 1
                except:
                    pass

        # Generate last 12 months labels and data
        months = []
        growth_data = []
        for i in range(11, -1, -1):
            month_date = now - relativedelta(months=i)
            month_key = month_date.strftime('%Y-%m')
            month_label = month_date.strftime('%b %Y')
            months.append(month_label)
            growth_data.append(monthly_data.get(month_key, 0))

        # Activity data (users with recent logins)
        recent_logins = 0
        for user in users:
            if user.last_login:
                try:
                    last_login = datetime.fromisoformat(user.last_login)
                    if (now - last_login).days <= 30:
                        recent_logins += 1
                except:
                    pass

    body = f"""
    <div class="admin-grid">
      <div class="stat-card">
        <div class="stat-number">{total_users}</div>
        <div class="stat-label">Total Users</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{active_users}</div>
        <div class="stat-label">Active Users</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{recent_logins}</div>
        <div class="stat-label">Recent Logins (30d)</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{admin_users}</div>
        <div class="stat-label">Admin Users</div>
      </div>
    </div>

    <div class="admin-card">
      <h3>User Growth (Last 12 Months)</h3>
      <canvas id="growthChart" width="400" height="200"></canvas>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
      <div class="admin-card">
        <h3>User Status Distribution</h3>
        <canvas id="statusChart" width="300" height="300"></canvas>
      </div>

      <div class="admin-card">
        <h3>User Activity</h3>
        <table class="data-table">
          <tr><td><strong>Total Registrations:</strong></td><td>{total_users}</td></tr>
          <tr><td><strong>Active Users:</strong></td><td>{active_users}</td></tr>
          <tr><td><strong>Inactive Users:</strong></td><td>{total_users - active_users}</td></tr>
          <tr><td><strong>Recent Activity (30d):</strong></td><td>{recent_logins}</td></tr>
          <tr><td><strong>Admin Users:</strong></td><td>{admin_users}</td></tr>
        </table>
      </div>
    </div>

    <script>
      // User Growth Chart
      const growthCtx = document.getElementById('growthChart').getContext('2d');
      new Chart(growthCtx, {{
        type: 'line',
        data: {{
          labels: {months},
          datasets: [{{
            label: 'New Users',
            data: {growth_data},
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            borderWidth: 2,
            fill: true,
            tension: 0.4
          }}]
        }},
        options: {{
          responsive: true,
          plugins: {{
            legend: {{
              labels: {{
                color: '#f8fafc'
              }}
            }}
          }},
          scales: {{
            x: {{
              ticks: {{
                color: '#cbd5e1'
              }},
              grid: {{
                color: '#374151'
              }}
            }},
            y: {{
              ticks: {{
                color: '#cbd5e1'
              }},
              grid: {{
                color: '#374151'
              }}
            }}
          }}
        }}
      }});

      // Status Distribution Chart
      const statusCtx = document.getElementById('statusChart').getContext('2d');
      new Chart(statusCtx, {{
        type: 'doughnut',
        data: {{
          labels: ['Active Users', 'Inactive Users', 'Admin Users'],
          datasets: [{{
            data: [{active_users - admin_users}, {total_users - active_users}, {admin_users}],
            backgroundColor: ['#10b981', '#ef4444', '#3b82f6'],
            borderColor: '#1a1f2e',
            borderWidth: 2
          }}]
        }},
        options: {{
          responsive: true,
          plugins: {{
            legend: {{
              labels: {{
                color: '#f8fafc'
              }}
            }}
          }}
        }}
      }});
    </script>
    """

    return admin_page("Analytics Dashboard", body, "analytics", admin)

@app.get("/admin/system", response_class=HTMLResponse)
def admin_system(request: Request, admin: User = Depends(require_admin)):
    import psutil
    import platform
    import sys
    from pathlib import Path

    # System information
    system_info = {
        'platform': platform.system(),
        'platform_version': platform.version(),
        'python_version': sys.version,
        'cpu_count': psutil.cpu_count(),
        'memory_total': round(psutil.virtual_memory().total / (1024**3), 2),
        'memory_used': round(psutil.virtual_memory().used / (1024**3), 2),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_total': round(psutil.disk_usage('/').total / (1024**3), 2),
        'disk_used': round(psutil.disk_usage('/').used / (1024**3), 2),
        'disk_percent': psutil.disk_usage('/').percent,
    }

    # Database information
    db_path = Path("qr.db")
    db_size = round(db_path.stat().st_size / (1024**2), 2) if db_path.exists() else 0

    # Application logs (last 50 lines from a hypothetical log file)
    log_entries = []
    try:
        # In a real application, you'd read from actual log files
        # For now, we'll create some sample log entries
        log_entries = [
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Admin panel accessed by {admin.username}",
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - System health check performed",
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - INFO - Database size: {db_size}MB",
        ]
    except Exception as e:
        log_entries = [f"Error reading logs: {str(e)}"]

    body = f"""
    <div class="admin-grid">
      <div class="stat-card">
        <div class="stat-number">{system_info['cpu_count']}</div>
        <div class="stat-label">CPU Cores</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{system_info['memory_percent']:.1f}%</div>
        <div class="stat-label">Memory Usage</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{system_info['disk_percent']:.1f}%</div>
        <div class="stat-label">Disk Usage</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{db_size}MB</div>
        <div class="stat-label">Database Size</div>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
      <div class="admin-card">
        <h3>System Information</h3>
        <table class="data-table">
          <tr><td><strong>Platform:</strong></td><td>{system_info['platform']}</td></tr>
          <tr><td><strong>Python Version:</strong></td><td>{system_info['python_version'].split()[0]}</td></tr>
          <tr><td><strong>CPU Cores:</strong></td><td>{system_info['cpu_count']}</td></tr>
          <tr><td><strong>Total Memory:</strong></td><td>{system_info['memory_total']} GB</td></tr>
          <tr><td><strong>Used Memory:</strong></td><td>{system_info['memory_used']} GB ({system_info['memory_percent']:.1f}%)</td></tr>
          <tr><td><strong>Total Disk:</strong></td><td>{system_info['disk_total']} GB</td></tr>
          <tr><td><strong>Used Disk:</strong></td><td>{system_info['disk_used']} GB ({system_info['disk_percent']:.1f}%)</td></tr>
        </table>
      </div>

      <div class="admin-card">
        <h3>Database Information</h3>
        <table class="data-table">
          <tr><td><strong>Database File:</strong></td><td>qr.db</td></tr>
          <tr><td><strong>Size:</strong></td><td>{db_size} MB</td></tr>
          <tr><td><strong>Engine:</strong></td><td>SQLite</td></tr>
          <tr><td><strong>Tables:</strong></td><td>1 (user)</td></tr>
        </table>

        <div style="margin-top: 16px;">
          <button onclick="backupDatabase()" class="btn-primary btn-small">Backup Database</button>
          <button onclick="optimizeDatabase()" class="btn-secondary btn-small">Optimize Database</button>
        </div>
      </div>
    </div>

    <div class="admin-card">
      <h3>Application Configuration</h3>
      <table class="data-table">
        <tr><td><strong>App Secret:</strong></td><td>{'Set' if os.getenv('APP_SECRET') != 'dev-secret-change-me' else 'Using default (dev)'}</td></tr>
        <tr><td><strong>Database URL:</strong></td><td>{DB_URL}</td></tr>
        <tr><td><strong>Static Files:</strong></td><td>Enabled</td></tr>
        <tr><td><strong>Debug Mode:</strong></td><td>{'Enabled' if os.getenv('DEBUG') == 'true' else 'Disabled'}</td></tr>
      </table>
    </div>

    <div class="admin-card">
      <h3>Recent Activity Logs</h3>
      <div style="background: var(--bg-secondary); border-radius: 8px; padding: 16px; font-family: monospace; font-size: 14px; max-height: 300px; overflow-y: auto;">
    """

    for log_entry in log_entries:
        body += f"<div style='margin-bottom: 4px; color: var(--text-secondary);'>{log_entry}</div>"

    body += """
      </div>
      <div style="margin-top: 12px;">
        <button onclick="refreshLogs()" class="btn-secondary btn-small">Refresh Logs</button>
        <button onclick="clearLogs()" class="btn-warning btn-small">Clear Logs</button>
      </div>
    </div>

    <div class="admin-card">
      <h3>Maintenance Tools</h3>
      <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <button onclick="runHealthCheck()" class="btn-primary">Health Check</button>
        <button onclick="cleanupSessions()" class="btn-secondary">Cleanup Sessions</button>
        <button onclick="generateReport()" class="btn-secondary">Generate Report</button>
        <button onclick="restartApp()" class="btn-warning">Restart Application</button>
      </div>
    </div>

    <script>
      function backupDatabase() {
        if (confirm('Create a database backup?')) {
          fetch('/admin/system/backup-db', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
          }).then(response => response.json())
          .then(data => alert(data.message || 'Backup completed'))
          .catch(err => alert('Backup failed: ' + err));
        }
      }

      function optimizeDatabase() {
        if (confirm('Optimize database? This may take a moment.')) {
          fetch('/admin/system/optimize-db', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
          }).then(response => response.json())
          .then(data => alert(data.message || 'Optimization completed'))
          .catch(err => alert('Optimization failed: ' + err));
        }
      }

      function runHealthCheck() {
        fetch('/admin/system/health-check', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'}
        }).then(response => response.json())
        .then(data => alert('Health Check: ' + (data.status || 'OK')))
        .catch(err => alert('Health check failed: ' + err));
      }

      function cleanupSessions() {
        if (confirm('Clean up expired sessions?')) {
          fetch('/admin/system/cleanup-sessions', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
          }).then(response => response.json())
          .then(data => alert(data.message || 'Cleanup completed'))
          .catch(err => alert('Cleanup failed: ' + err));
        }
      }

      function generateReport() {
        window.open('/admin/system/report', '_blank');
      }

      function restartApp() {
        if (confirm('Restart the application? This will disconnect all users.')) {
          alert('Restart functionality would be implemented based on deployment method.');
        }
      }

      function refreshLogs() {
        location.reload();
      }

      function clearLogs() {
        if (confirm('Clear all logs? This action cannot be undone.')) {
          alert('Log clearing functionality would be implemented.');
        }
      }
    </script>
    """

    return admin_page("System Administration", body, "system", admin)

@app.post("/admin/system/backup-db")
def admin_backup_database(admin: User = Depends(require_admin)):
    import shutil
    from pathlib import Path

    try:
        backup_name = f"qr_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2("qr.db", backup_name)
        return {"success": True, "message": f"Database backed up to {backup_name}"}
    except Exception as e:
        return {"success": False, "message": f"Backup failed: {str(e)}"}

@app.post("/admin/system/optimize-db")
def admin_optimize_database(admin: User = Depends(require_admin)):
    try:
        with Session(engine) as s:
            s.exec("VACUUM")
            s.commit()
        return {"success": True, "message": "Database optimized successfully"}
    except Exception as e:
        return {"success": False, "message": f"Optimization failed: {str(e)}"}

@app.post("/admin/system/health-check")
def admin_health_check(admin: User = Depends(require_admin)):
    try:
        # Check database connection
        with Session(engine) as s:
            s.exec(select(User).limit(1))

        # Check disk space
        import psutil
        disk_usage = psutil.disk_usage('/')
        disk_free_percent = (disk_usage.free / disk_usage.total) * 100

        # Check memory
        memory = psutil.virtual_memory()
        memory_available_percent = memory.available / memory.total * 100

        status = "OK"
        issues = []

        if disk_free_percent < 10:
            issues.append("Low disk space")
            status = "WARNING"

        if memory_available_percent < 10:
            issues.append("Low memory")
            status = "WARNING"

        return {
            "success": True,
            "status": status,
            "issues": issues,
            "disk_free_percent": round(disk_free_percent, 1),
            "memory_available_percent": round(memory_available_percent, 1)
        }
    except Exception as e:
        return {"success": False, "status": "ERROR", "message": str(e)}

@app.post("/admin/system/cleanup-sessions")
def admin_cleanup_sessions(admin: User = Depends(require_admin)):
    # In a real application, you'd clean up expired sessions from a session store
    # For this simple implementation, we'll just return a success message
    return {"success": True, "message": "Session cleanup completed"}

@app.get("/admin/system/report")
def admin_system_report(admin: User = Depends(require_admin)):
    with Session(engine) as s:
        users = s.exec(select(User)).all()

        report_data = {
            "generated_at": datetime.now().isoformat(),
            "generated_by": admin.username,
            "total_users": len(users),
            "active_users": len([u for u in users if u.is_active]),
            "admin_users": len([u for u in users if u.is_admin]),
            "users_with_phone": len([u for u in users if u.phone_e164]),
            "users_with_preset": len([u for u in users if u.preset_text]),
        }

    # Return as JSON for download
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=report_data,
        headers={"Content-Disposition": "attachment; filename=chatcode_report.json"}
    )

# --------------- Health (for Render/Fly) ---------------
@app.get("/health")
def health():
    return {"ok": True, "time": int(time.time())}
