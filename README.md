# ChatCode - WhatsApp QR Code Generator

A modern, professional web application for creating WhatsApp QR codes that enable instant messaging connections. Perfect for business cards, events, storefronts, and networking.

## Features

- **Instant WhatsApp Connection**: QR codes open WhatsApp chats immediately
- **Professional Design**: Clean, high-quality QR codes suitable for business use
- **Universal Compatibility**: Works with any QR scanner on iOS, Android, or desktop
- **Custom Messages**: Set preset messages that appear when someone scans your QR
- **Download & Share**: High-resolution PNG downloads and public QR pages
- **Easy Updates**: Change phone numbers or messages without regenerating QR codes

## Tech Stack

- **Backend**: FastAPI + Uvicorn
- **Database**: SQLite with SQLModel
- **Authentication**: Session-based with secure password hashing (bcrypt)
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

4. Run the application:
```bash
uvicorn app:app --reload
```

5. Open your browser and navigate to `http://127.0.0.1:8000`

## Usage

1. **Create Account**: Register with your username and WhatsApp phone number (E.164 format)
2. **Generate QR**: Your personalized QR code is created instantly
3. **Share & Connect**: Download, print, or share your QR code

## Phone Number Format

Use E.164 international format for phone numbers:
- Format: `+[country code][phone number]`
- Example: `+77011234567` (Kazakhstan)
- Example: `+1234567890` (US)

## Environment Variables

- `APP_SECRET`: Secret key for session signing (optional, defaults to dev key)

## Deployment

### Quick Deploy Options

- **Render/Fly.io/Dokku**: Add a `Procfile` with:
  ```
  web: uvicorn app:app --host 0.0.0.0 --port $PORT
  ```
- **For persistence**: Mount a volume for `qr.db`

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
