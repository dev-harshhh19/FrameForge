# FrameForge: AI-Powered Marketing Video Generation Bot

FrameForge is an automated video generation engine that accepts structured product metadata (JSON) and digital assets to produce narrated, broadcast-ready marketing videos with synchronized subtitles. 

This repository constitutes the submission for **Task 2 (Project-Based Task)**.

## 1. Problem Understanding
Creating marketing videos traditionally requires manual storyboarding, voiceover recording, and timeline editing for *every single product*. A hardcoded demo or single-pass script is insufficient for modern marketing teams who need to generate hundreds of localized product videos. 

FrameForge solves this by providing a truly reusable, multi-product engine. It dynamically handles text-to-speech (TTS), visual generation, timing synchronization, and final FFmpeg multiplexing entirely based on the input JSON structure. This allows non-technical team members to generate professional videos at scale without touching the underlying code or video editing software.

## 2. Pipeline & Architecture

FrameForge uses a decoupled, multi-stage pipeline processing architecture.

[View the full Architecture Diagram and Tooling Details in `architecture.md`](architecture.md)

## 3. Scalability & Limit Handling (No Hard Caps)
FrameForge does not impose artificial caps on video length, scene count, or generation frequency. It manages provider-side limits (e.g., rate limits, API quotas, maximum generation ceilings) using the following robust strategies:

1. **Scene Splitting & Batching**: Rather than sending a 5-minute script to an API and risking a timeout or size limit error, FrameForge splits the script into short, independent scenes (typically 5-10 seconds). It processes these scenes individually and concatenates them locally.
2. **Cascading Provider Fallbacks**: The `TTSPipeline` uses a resilient fallback chain. If the primary cloud provider (Google Gemini) hits a rate limit or API failure, it automatically fails over to secondary keys, then to ElevenLabs, and ultimately falls back to a fully local, offline TTS engine (`libflite`).
3. **Asynchronous Queueing**: For the web dashboard, incoming generation requests are offloaded to an asynchronous background worker queue (`job_queue`). This prevents the Flask server from blocking, gracefully manages high-volume traffic, and serializes heavy FFmpeg workloads to prevent CPU thrashing.

## 4. Setup and Usability
FrameForge is designed so that a non-technical team member can submit a product and receive a video without writing code.

### Installation
1. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
2. (Optional) Provide API keys in the `.env` file for cloud generation. The system will fall back to local rendering if these are omitted.

### Usage: Web Dashboard (For Non-Technical Users)
Simply run the web server:
```bash
python app.py
```
Open your browser to `http://127.0.0.1:5000`. Fill out the simple web form with your product's name, description, and features, and click "Generate". The dashboard tracks progress and provides a download link.

### Usage: CLI (For Automation/Developers)
For batch generation or CI/CD pipelines, use the CLI:
```bash
python cli.py generate --json samples/task1_jalsetu.json
```

## 5. Code Quality & Demonstration
The codebase is modular, cleanly separated into core processing engines (`core/pipeline.py`, `core/tts_providers.py`), and thoroughly commented. The bot has been tested end-to-end with multiple distinct sample products (including `samples/BMW_M5.json` and `samples/task1_jalsetu.json`) to prove generalization across different use cases.
