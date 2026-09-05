#!/usr/bin/env python3
"""
Simple web dashboard so a non-technical teammate can submit a product and
get a video back without touching code.

Run:  python app.py   then open http://localhost:5000
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from flask import Flask, request, render_template, redirect, url_for, send_from_directory, jsonify
from werkzeug.utils import secure_filename

from core.models import ProductInput
from core.queue_manager import job_queue
from core.pipeline import get_status, JOBS_DIR

app = Flask(__name__)
UPLOAD_DIR = Path("assets/uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    form = request.form
    logo_path = None
    if "logo" in request.files and request.files["logo"].filename:
        f = request.files["logo"]
        dest = UPLOAD_DIR / secure_filename(f.filename)
        f.save(dest)
        logo_path = str(dest)

    image_paths = []
    for f in request.files.getlist("images"):
        if f and f.filename:
            dest = UPLOAD_DIR / secure_filename(f.filename)
            f.save(dest)
            image_paths.append(str(dest))

    if form.get("raw_json") and form.get("raw_json").strip():
        try:
            data = json.loads(form.get("raw_json"))
            product = ProductInput.from_dict(data)
        except json.JSONDecodeError:
            return render_template("index.html", error="Invalid JSON format."), 400
    else:
        name = form.get("name", "").strip()
        description = form.get("description", "").strip()
        
        if not name or not description:
            return render_template("index.html", error="Name and description are required."), 400
            
        product = ProductInput.from_dict({
            "name": name,
            "description": description,
            "features": form.get("features", ""),
            "target_audience": form.get("target_audience", "").strip(),
            "call_to_action": form.get("call_to_action") or "Learn more today.",
            "brand_color": form.get("brand_color") or "#1D4ED8",
            "tone": form.get("tone") or "energetic",
            "voice": form.get("voice") or "slt",
            "logo_path": logo_path,
            "image_paths": image_paths,
            "notify_webhook": form.get("notify_webhook") or None,
            "notify_email": form.get("notify_email") or None,
            "mode": form.get("mode") or "local",
        })

    job_id = job_queue.submit(product)
    return redirect(url_for("status_page", job_id=job_id))


@app.route("/status/<job_id>", methods=["GET"])
def status_page(job_id):
    return render_template("status.html", job_id=job_id)


@app.route("/api/status/<job_id>", methods=["GET"])
def api_status(job_id):
    status = get_status(job_id)
    if not status:
        return jsonify({"status": "unknown"}), 404
    return jsonify(status)


@app.route("/api/jobs", methods=["GET"])
def api_jobs():
    """List all jobs, newest first - powers a simple 'all videos' dashboard view."""
    jobs = []
    for p in sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            jobs.append(json.loads(p.read_text()))
        except Exception:
            continue
    return jsonify(jobs)


_START_TIME = time.time()


@app.route("/api/health", methods=["GET"])
def api_health():
    """
    Genuine system health probe.
    Checks every real dependency the pipeline needs to produce a video:
    FFmpeg binary, TTS provider import, disk writability, worker threads,
    and actual job counts read from the jobs/ directory on disk.
    """
    checks = {}
    overall = "healthy"

    # 1. Uptime
    uptime_sec = round(time.time() - _START_TIME, 1)

    # 2. FFmpeg binary -- the assembler will fail without it
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5,
        )
        version_line = result.stdout.split("\n")[0] if result.returncode == 0 else None
        checks["ffmpeg"] = {
            "ok": result.returncode == 0,
            "version": version_line,
        }
    except FileNotFoundError:
        checks["ffmpeg"] = {"ok": False, "error": "ffmpeg binary not found in PATH"}
        overall = "degraded"
    except Exception as e:
        checks["ffmpeg"] = {"ok": False, "error": str(e)}
        overall = "degraded"

    # 3. TTS provider availability -- try to import and instantiate
    try:
        from core.tts_providers import FliteLocalTTSProvider
        FliteLocalTTSProvider()
        checks["tts_local"] = {"ok": True, "provider": "FliteLocalTTSProvider"}
    except Exception as e:
        checks["tts_local"] = {"ok": False, "error": str(e)}
        overall = "degraded"

    # 4. Disk writability -- actually try writing a temp file to outputs/
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        probe_file = OUTPUT_DIR / ".health_probe"
        probe_file.write_text("ok")
        probe_file.unlink()
        disk = shutil.disk_usage(OUTPUT_DIR)
        checks["disk"] = {
            "ok": True,
            "writable": True,
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "total_gb": round(disk.total / (1024 ** 3), 2),
        }
    except Exception as e:
        checks["disk"] = {"ok": False, "writable": False, "error": str(e)}
        overall = "unhealthy"

    # 5. Worker threads -- check each thread is actually alive
    workers_alive = 0
    workers_dead = 0
    for t in job_queue._workers:
        if t.is_alive():
            workers_alive += 1
        else:
            workers_dead += 1
    checks["workers"] = {
        "ok": workers_dead == 0 and workers_alive > 0,
        "alive": workers_alive,
        "dead": workers_dead,
        "queue_depth": job_queue.queue_depth(),
    }
    if workers_dead > 0:
        overall = "degraded"
    if workers_alive == 0 and job_queue._started:
        overall = "unhealthy"

    # 6. Real job counts from disk
    counts = {"queued": 0, "scripting": 0, "rendering_scenes": 0,
              "assembling": 0, "completed": 0, "failed": 0}
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for p in JOBS_DIR.glob("*.json"):
        try:
            s = json.loads(p.read_text()).get("status", "unknown")
            if s in counts:
                counts[s] += 1
        except Exception:
            continue
    checks["jobs"] = counts

    status_code = 200 if overall == "healthy" else 503

    return jsonify({
        "status": overall,
        "uptime_seconds": uptime_sec,
        "checks": checks,
    }), status_code


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/outputs/<path:filename>", methods=["GET"])
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename)

@app.route("/privacy", methods=["GET"])
def privacy():
    return render_template("privacy.html")

@app.route("/terms", methods=["GET"])
def terms():
    return render_template("terms.html")


if __name__ == "__main__":
    job_queue.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
