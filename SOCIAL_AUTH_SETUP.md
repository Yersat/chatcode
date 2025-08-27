# Social Authentication Setup Guide

This guide provides detailed instructions for setting up Google and GitHub OAuth authentication in ChatCode.

## Overview

ChatCode supports social authentication through:
- **Google OAuth 2.0**: Sign in with Google accounts
- **GitHub OAuth**: Sign in with GitHub accounts

Both providers are optional and can be configured independently.

## Prerequisites

- ChatCode application running locally or deployed
- Access to Google Cloud Console (for Google OAuth)
- GitHub account with developer access (for GitHub OAuth)

## Google OAuth Setup

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Enter project name (e.g., "ChatCode OAuth")
4. Click **Create**

### Step 2: Enable APIs

1. In the Google Cloud Console, go to **APIs & Services** → **Library**
2. Search for "Google+ API" or "People API"
3. Click on the API and click **Enable**

### Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services** → **OAuth consent screen**
2. Choose **External** user type (unless you have a Google Workspace)
3. Fill in required fields:
   - **App name**: ChatCode
   - **User support email**: Your email
   - **Developer contact information**: Your email
4. Click **Save and Continue**
5. Skip **Scopes** section (click **Save and Continue**)
6. Add test users if needed, then **Save and Continue**

### Step 4: Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth 2.0 Client IDs**
3. Choose **Web application**
4. Set **Name**: ChatCode Web Client
5. Add **Authorized redirect URIs**:
   - For local development: `http://127.0.0.1:8000/auth/google/callback`
   - For production: `https://yourdomain.com/auth/google/callback`
6. Click **Create**
7. Copy the **Client ID** and **Client Secret**

## GitHub OAuth Setup

### Step 1: Create OAuth App

1. Go to [GitHub Settings](https://github.com/settings/profile)
2. Click **Developer settings** (bottom left)
3. Click **OAuth Apps** → **New OAuth App**

### Step 2: Configure OAuth App

Fill in the application details:
- **Application name**: ChatCode
- **Homepage URL**: 
  - Local: `http://127.0.0.1:8000`
  - Production: `https://yourdomain.com`
- **Application description**: WhatsApp QR Code Generator with Social Login
- **Authorization callback URL**:
  - Local: `http://127.0.0.1:8000/auth/github/callback`
  - Production: `https://yourdomain.com/auth/github/callback`

### Step 3: Get Credentials

1. Click **Register application**
2. Copy the **Client ID**
3. Click **Generate a new client secret**
4. Copy the **Client Secret** (save it immediately, you won't see it again)

## Environment Configuration

### Step 1: Create Environment File

Copy the example environment file:
```bash
cp .env.example .env
```

### Step 2: Configure OAuth Credentials

Edit the `.env` file with your credentials:

```bash
# Application Secret (REQUIRED - generate a secure random string)
APP_SECRET=your-super-secret-key-change-me-in-production

# Base URL (change for production)
BASE_URL=http://127.0.0.1:8000

# Google OAuth (optional)
GOOGLE_CLIENT_ID=your-google-client-id-here
GOOGLE_CLIENT_SECRET=your-google-client-secret-here

# GitHub OAuth (optional)
GITHUB_CLIENT_ID=your-github-client-id-here
GITHUB_CLIENT_SECRET=your-github-client-secret-here
```

### Step 3: Generate Secure APP_SECRET

For production, generate a secure secret:

```bash
# Using Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Using OpenSSL
openssl rand -base64 32
```

## Testing the Setup

### Step 1: Run Tests

```bash
python test_social_auth.py
```

This will verify:
- OAuth configuration is correct
- All required components are working
- Database schema is up to date

### Step 2: Manual Testing

1. Start the application:
   ```bash
   uvicorn app:app --reload
   ```

2. Open `http://127.0.0.1:8000/login`

3. You should see social login buttons for configured providers

4. Test the OAuth flow:
   - Click a social login button
   - Complete authentication with the provider
   - Verify you're redirected back and logged in

## Production Deployment

### Security Considerations

1. **Use HTTPS**: OAuth requires HTTPS in production
2. **Secure APP_SECRET**: Use a strong, randomly generated secret
3. **Environment Variables**: Never commit secrets to version control
4. **Update Redirect URIs**: Use your production domain in OAuth settings

### Environment Variables for Production

```bash
# Required
APP_SECRET=your-production-secret-key
BASE_URL=https://yourdomain.com

# OAuth credentials
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
```

### Update OAuth Provider Settings

1. **Google Cloud Console**:
   - Add production redirect URI: `https://yourdomain.com/auth/google/callback`
   - Update authorized domains if needed

2. **GitHub OAuth App**:
   - Update Homepage URL: `https://yourdomain.com`
   - Update Authorization callback URL: `https://yourdomain.com/auth/github/callback`

## Troubleshooting

### Common Issues

1. **"Provider not configured" error**:
   - Check that environment variables are set correctly
   - Restart the application after changing `.env`

2. **"Invalid OAuth state" error**:
   - Clear browser cookies and try again
   - Check that APP_SECRET is consistent

3. **"Redirect URI mismatch" error**:
   - Verify callback URLs in OAuth provider settings
   - Ensure BASE_URL matches your actual domain

4. **Social login buttons not appearing**:
   - Check that OAuth credentials are set in `.env`
   - Verify the application can read environment variables

### Debug Mode

Enable debug logging by setting:
```bash
DEBUG=true
```

This will provide more detailed error messages in the console.

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Run the test suite: `python test_social_auth.py`
3. Check application logs for detailed error messages
4. Verify OAuth provider settings match your configuration

For additional help, contact support through the application.
