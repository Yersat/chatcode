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
import os, re, secrets, time
from itsdangerous import TimestampSigner, BadSignature

# ---------------------- Config ----------------------
DB_URL = "sqlite:///qr.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
APP_SECRET = os.getenv("APP_SECRET", "dev-secret-change-me")
signer = TimestampSigner(APP_SECRET)

# ---------------------- Models ----------------------
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    phone_e164: str | None = None
    preset_text: str | None = None  # optional prefilled message

# ---------------------- DB Init ----------------------
SQLModel.metadata.create_all(engine)

# ---------------------- App ----------------------
app = FastAPI(title="ChatCode")
app.mount("/static", StaticFiles(directory="static"), name="static")

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
        return int(raw)
    except BadSignature:
        return None

def get_current_user(request: Request) -> User | None:
    cookie = request.cookies.get("session")
    if not cookie:
        return None
    user_id = read_session_cookie(cookie)
    if not user_id:
        return None
    with Session(engine) as s:
        return s.get(User, user_id)

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
          <a href="/login">Login</a>
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
    return page("Register", f"""
    <h1>Create your account</h1>
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
          <input required name=phone placeholder='+77011234567' pattern="\+[1-9]\d{{8,14}}">
        </div>
        <div>
          <label>Optional preset message</label>
          <input name=preset placeholder='Hi, saw your QR at ...'>
        </div>
      </div>
      <button>Create</button>
    </form>
    <p class=muted>Already have an account? <a href='/login'>Sign in</a></p>
    """)

@app.post("/register")
def register_action(username: str = Form(...), password: str = Form(...), phone: str = Form(...), preset: str = Form("")):
    if not E164_RE.match(phone):
        raise HTTPException(400, "Phone must be in E.164 format, e.g., +77011234567")
    with Session(engine) as s:
        if s.exec(select(User).where(User.username == username)).first():
            raise HTTPException(400, "Username already taken")
        u = User(username=username, password_hash=hash_password(password), phone_e164=phone, preset_text=preset.strip() or None)
        s.add(u); s.commit(); s.refresh(u)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("session", create_session_cookie(u.id), httponly=True, max_age=60*60*24*30)
    return resp

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page("Sign in", f"""
    <h1>Sign in</h1>
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
        if not u or not verify_password(password, u.password_hash):
            raise HTTPException(401, "Invalid credentials")
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("session", create_session_cookie(u.id), httponly=True, max_age=60*60*24*30)
        return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login")
    link = f"https://wa.me/{user.phone_e164.lstrip('+')}"
    if user.preset_text:
        import urllib.parse
        link += "?text=" + urllib.parse.quote(user.preset_text)
    body = f"""
    <h1>Your QR is ready</h1>
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
          <input name=phone value='{user.phone_e164}' pattern="\+[1-9]\d{{8,14}}">
          <label>Optional preset message</label>
          <input name=preset value='{user.preset_text or ''}'>
          <button>Save</button>
        </form>
        <p class=note>Anyone scanning your QR will be taken to this link and can message you immediately in WhatsApp.</p>
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
        if user.preset_text:
            import urllib.parse
            link += "?text=" + urllib.parse.quote(user.preset_text)
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
    if user.preset_text:
        import urllib.parse
        link += "?text=" + urllib.parse.quote(user.preset_text)
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

# --------------- Health (for Render/Fly) ---------------
@app.get("/health")
def health():
    return {"ok": True, "time": int(time.time())}
