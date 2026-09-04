# FrameForge User Guide

## Overview
FrameForge produces direct, professional marketing videos generated from strict JSON payloads. The system avoids generic "AI-generated" aesthetics by adhering to rigid, code-driven typography, layout, and copy constraints. 

## Command Line Interface
You can bypass the web UI and use the CLI to test generation:
```bash
python cli.py generate --json samples/BMW_M5.json
```
This process is synchronous and will output the final `.mp4` and `.srt` files into the `outputs/` directory.

## Best Practices
- Keep descriptions precise and feature lists under 10 items.
- Avoid vague hero text or embellished metrics in your JSON payload. 
- Ensure high-resolution product imagery for the best output quality.
