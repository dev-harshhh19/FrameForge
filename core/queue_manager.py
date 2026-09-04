"""
Job queue with a bounded worker pool but an UNBOUNDED queue.

Why this matters for "no cap on video count / generation frequency":
submission (enqueue) and rendering (dequeue + generate_video) are
decoupled. A non-technical user (or a script) can submit any number of
jobs in a burst; they land in `jobs/*.json` with status="queued"
immediately and get a job_id back right away. A small pool of worker
threads (WORKER_COUNT, configurable via env var) drains the queue at a
sustainable rate. This means:

  * No request is ever rejected because "too many videos already
    generated" -- there's no counter being checked against a limit.
  * Throughput scales horizontally: run more worker processes (even on
    other machines, since the queue is just files under jobs/ + work/)
    to render more videos in parallel without changing any code.
  * If the process restarts, `requeue_pending()` picks queued/in-flight
    jobs back up from disk instead of losing them.

For a heavier production load, swap `InProcessQueue` for Celery + Redis/
RabbitMQ or AWS SQS + worker fleet -- the public interface
(`submit`, `worker_loop`) is deliberately the same shape either way.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from core.models import ProductInput
from core.pipeline import generate_video, _update_status, JOBS_DIR

WORKER_COUNT = int(os.environ.get("VIDEO_BOT_WORKERS", "2"))


class InProcessQueue:
    def __init__(self, worker_count: int = WORKER_COUNT):
        self._q: "queue.Queue[ProductInput]" = queue.Queue()  # unbounded
        self._worker_count = worker_count
        self._workers = []
        self._started = False

    def start(self):
        if self._started:
            return
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        for i in range(self._worker_count):
            t = threading.Thread(target=self._worker_loop, name=f"video-worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        self._started = True
        self.requeue_pending()

    def submit(self, product: ProductInput) -> str:
        self.start()
        _update_status(product.job_id, status="queued", product_name=product.name,
                        queued_at=time.time())
        self._q.put(product)
        return product.job_id

    def requeue_pending(self):
        """On startup, pick back up any job that was queued/rendering when
        the process last stopped, so bursts survive a restart."""
        if not JOBS_DIR.exists():
            return
        for p in JOBS_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            if data.get("status") in ("queued", "scripting", "rendering_scenes", "assembling"):
                prod = data.get("product")
                if prod:
                    self._q.put(ProductInput.from_dict(prod))

    def _worker_loop(self):
        while True:
            product = self._q.get()
            try:
                generate_video(product)
            except Exception as e:  # noqa: BLE001
                _update_status(product.job_id, status="failed", error=str(e))
            finally:
                self._q.task_done()

    def queue_depth(self) -> int:
        return self._q.qsize()


# a single shared queue instance for the web app / CLI to import
job_queue = InProcessQueue()
