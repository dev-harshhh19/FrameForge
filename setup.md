# FrameForge Setup Guide

## Prerequisites
- Python 3.9+
- FFmpeg installed and available on PATH
- Pillow for image generation

## Local Development
1. Clone the repository and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the local server:
   ```bash
   python app.py
   ```
3. Navigate to `http://localhost:5000` to submit jobs.

## Production
To deploy FrameForge in a production environment:
- **Custom Domain:** Configure a reverse proxy (e.g., Nginx) and point your A record to the server IP. Secure with Let's Encrypt SSL.
- **Process Manager:** Run the application via `gunicorn` combined with a process manager like `systemd` or `pm2`.
- **Environment Variables:** Provide production credentials via a `.env` file (e.g., cloud TTS credentials if bypassing the local flite engine).
