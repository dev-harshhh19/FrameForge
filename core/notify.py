"""
Delivery / notification stage.

Kept intentionally simple: writes a delivery record to jobs/<id>.json (the
same status file the web UI and CLI already poll) and, if the caller gave
a webhook URL, POSTs a completion payload to it. Swap `_post_webhook` for
Slack/email/S3-upload calls in a real deployment; the pipeline only
depends on `notify()` being called with the final video path.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Optional


def notify(job_id: str, video_path: Path, srt_path: Optional[Path],
           webhook_url: Optional[str] = None, email: Optional[str] = None,
           log_dir: Path = Path("logs")) -> dict:
    payload = {
        "job_id": job_id,
        "status": "completed",
        "video_path": str(video_path),
        "captions_path": str(srt_path) if srt_path else None,
        "notify_email": email,
    }
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"delivery_{job_id}.json").write_text(json.dumps(payload, indent=2))

    if webhook_url:
        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            payload["webhook_delivered"] = True
        except Exception as e:  # noqa: BLE001
            payload["webhook_delivered"] = False
            payload["webhook_error"] = str(e)
    return payload
