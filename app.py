#!/usr/bin/env python3
"""
Simple web dashboard so a non-technical teammate can submit a product and
get a video back without touching code.

Run:  python app.py   then open http://localhost:5000
"""
from __future__ import annotations

import json
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
