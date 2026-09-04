# FrameForge

FrameForge is an automated video generation engine that accepts structured product metadata and digital assets to produce narrated, broadcast-ready marketing videos with synchronized subtitles.

## Quick Start

1. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the web UI:
   ```bash
   python app.py
   ```
3. Generate via CLI:
   ```bash
   python cli.py generate --json samples/BMW_M5.json
   ```

## Production Deployment & Custom Domain

To launch FrameForge in production, you must:
1. Deploy the Flask application via gunicorn or a similar WSGI server.
2. Connect a custom domain by pointing your DNS A record to your production server's IP address and configuring a reverse proxy (e.g., Nginx or Caddy) to handle SSL/TLS.
3. Provide real API keys in the `.env` file for cloud rendering if desired.

See `setup.md` and `guide.md` for extended configuration details.

## Handling Provider Limits and Scale

FrameForge is designed to cleanly manage provider-side rate limits (TTS quotas, text-to-video generation ceilings, etc.) without halting production:
- **Fallback Chains**: We use a cascading provider model (e.g., `TTSPipeline`). If a primary cloud TTS provider hits a rate limit or goes offline, the system automatically falls back to secondary cloud providers or a fully local, offline engine (`libflite` via FFmpeg).
- **Asynchronous Queueing**: Web requests immediately offload generation jobs to an asynchronous background queue (`job_queue`). This ensures the HTTP server isn't blocked and allows controlled, serialized execution of heavy tasks.
- **Scene Splitting**: Long videos are broken down into short, independent scenes (typically 5-10 seconds). This inherently batches API requests to visual and audio providers, allowing us to stay under per-request size caps, stream results in parallel, and retry only the specific scenes that failed.
