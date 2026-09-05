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
    """Lightweight health check for monitoring and deployment verification."""
    uptime_seconds = round(time.time() - _START_TIME, 1)

    # Count jobs by status
    pending = 0
    running = 0
    completed = 0
    failed = 0
    for p in JOBS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            s = data.get("status", "unknown")
            if s == "queued":
                pending += 1
            elif s == "running":
                running += 1
            elif s == "done":
                completed += 1
            elif s == "error":
                failed += 1
        except Exception:
            continue

    # Disk usage for outputs directory
    disk = shutil.disk_usage(OUTPUT_DIR)
    disk_free_gb = round(disk.free / (1024 ** 3), 2)

    return jsonify({
        "status": "healthy",
        "uptime_seconds": uptime_seconds,
        "jobs": {
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
        },
        "disk_free_gb": disk_free_gb,
        "worker_alive": job_queue.worker.is_alive() if hasattr(job_queue, "worker") else None,
    })


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
