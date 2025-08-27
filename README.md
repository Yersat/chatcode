# ChatCode - WhatsApp QR Code Generator

A modern, professional web application for creating WhatsApp QR codes that enable instant messaging connections. Perfect for business cards, events, storefronts, and networking.

## Features

- **Instant WhatsApp Connection**: QR codes open WhatsApp chats immediately
- **Professional Design**: Clean, high-quality QR codes suitable for business use
- **Universal Compatibility**: Works with any QR scanner on iOS, Android, or desktop
- **Custom Messages**: Set preset messages that appear when someone scans your QR
- **Download & Share**: High-resolution PNG downloads and public QR pages
- **Easy Updates**: Change phone numbers or messages without regenerating QR codes
- **Social Authentication**: Sign up and login with Google or GitHub accounts
- **Profile Integration**: Automatically sync profile information from social providers
- **Secure OAuth**: Industry-standard OAuth 2.0 implementation with CSRF protection

## Tech Stack

- **Backend**: FastAPI + Uvicorn
- **Database**: SQLite with SQLModel
- **Authentication**: Session-based with secure password hashing (bcrypt) + OAuth 2.0
- **Social Login**: Google OAuth and GitHub OAuth integration
- **QR Generation**: Python qrcode library with PIL
- **Frontend**: Modern HTML/CSS with responsive design
- **Styling**: Custom CSS with dark theme and professional animations

## Quick Start

### Prerequisites

- Python 3.8+
- pip (Python package manager)

### Installation

1. Clone the repository:
```bash
git clone git@github.com:Yersat/chatcode.git
cd chatcode
```

2. Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. (Optional) Set up social authentication:
```bash
cp .env.example .env
# Edit .env file with your OAuth credentials (see Social Authentication Setup below)
```

5. Run database migration (if upgrading from older version):
```bash
python migrate_db.py
```

6. Run the application:
```bash
uvicorn app:app --reload
```

7. Open your browser and navigate to `http://127.0.0.1:8000`

## Usage

### Traditional Registration
1. **Create Account**: Register with your username and WhatsApp phone number (E.164 format)
2. **Generate QR**: Your personalized QR code is created instantly
3. **Share & Connect**: Download, print, or share your QR code

### Social Authentication
1. **Quick Sign Up**: Click "Sign up with Google" or "Sign up with GitHub" on the registration page
2. **Complete Setup**: Add your WhatsApp phone number to create your QR code
3. **Profile Sync**: Your name and profile picture are automatically synced from your social account

## Phone Number Format

Use E.164 international format for phone numbers:
- Format: `+[country code][phone number]`
- Example: `+77011234567` (Kazakhstan)
- Example: `+1234567890` (US)

## Social Authentication Setup

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API
4. Go to **Credentials** > **Create Credentials** > **OAuth 2.0 Client IDs**
5. Set **Authorized redirect URIs** to: `http://127.0.0.1:8000/auth/google/callback` (for local development)
6. Copy the **Client ID** and **Client Secret**

### GitHub OAuth Setup

1. Go to [GitHub Developer Settings](https://github.com/settings/developers)
2. Click **New OAuth App**
3. Fill in the application details:
   - **Application name**: ChatCode
   - **Homepage URL**: `http://127.0.0.1:8000`
   - **Authorization callback URL**: `http://127.0.0.1:8000/auth/github/callback`
4. Copy the **Client ID** and **Client Secret**

### Environment Configuration

Create a `.env` file in the project root:

```bash
# Application Secret (required)
APP_SECRET=your-super-secret-key-change-me-in-production

# Base URL (change for production)
BASE_URL=http://127.0.0.1:8000

# Google OAuth (optional)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# GitHub OAuth (optional)
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
```

## Environment Variables

- `APP_SECRET`: Secret key for session signing (required for production)
- `BASE_URL`: Base URL for OAuth callbacks (defaults to http://127.0.0.1:8000)
- `GOOGLE_CLIENT_ID`: Google OAuth client ID (optional)
- `GOOGLE_CLIENT_SECRET`: Google OAuth client secret (optional)
- `GITHUB_CLIENT_ID`: GitHub OAuth client ID (optional)
- `GITHUB_CLIENT_SECRET`: GitHub OAuth client secret (optional)

## Deployment

### Quick Deploy Options

- **Render/Fly.io/Dokku**: Add a `Procfile` with:
  ```
  web: uvicorn app:app --host 0.0.0.0 --port $PORT
  ```
- **For persistence**: Mount a volume for `qr.db`
- **Environment Variables**: Set OAuth credentials and APP_SECRET in production

## Testing

Run the test suite to verify social authentication setup:

```bash
python test_social_auth.py
```

This will check:
- Application startup and imports
- OAuth configuration
- Database schema
- Route definitions
- Helper functions

## Troubleshooting

### Social Login Not Working

1. **Check OAuth Configuration**: Ensure client IDs and secrets are set in `.env`
2. **Verify Redirect URIs**: Make sure callback URLs match in OAuth provider settings
3. **Check Logs**: Look for OAuth errors in the console output
4. **Test Environment**: Ensure `BASE_URL` matches your actual domain

### Database Issues

If you encounter database errors after upgrading:

```bash
# Run the migration script
python migrate_db.py

# Or start fresh (WARNING: deletes all data)
rm qr.db
python app.py  # Will create new database with all fields
```

### Common OAuth Errors

- **"Invalid OAuth state"**: CSRF protection triggered, try clearing browser cookies
- **"Provider not configured"**: OAuth credentials not set in environment variables
- **"Redirect URI mismatch"**: Update callback URLs in OAuth provider settings

## Support

- **Phone**: +77019601017
- **WhatsApp**: [Contact Support](https://wa.me/77019601017?text=Hi%2C%20I%20need%20help%20with%20ChatCode)

## License

This project is licensed under the MIT License.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

Built with ❤️ for instant WhatsApp connections
