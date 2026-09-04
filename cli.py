#!/usr/bin/env python3
"""
CLI interface.

Two modes:

  # one-off, synchronous - waits and prints the output path (good for demos/tests)
  python cli.py generate --json samples/sample_1_saas.json

  # fire-and-forget via the queue - returns immediately with a job id;
  # check progress any time with `python cli.py status <job_id>`
  python cli.py submit --json samples/sample_1_saas.json
  python cli.py status <job_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.models import ProductInput
from core.pipeline import generate_video, get_status
from core.queue_manager import job_queue


def _load_product(json_path: str) -> ProductInput:
    data = json.loads(Path(json_path).read_text())
    return ProductInput.from_dict(data)


def cmd_generate(args):
    product = _load_product(args.json)
    product.mode = args.mode
    print(f"[generate] job_id={product.job_id} product={product.name!r} "
          f"features={len(product.features)} mode={product.mode} -> rendering synchronously...")
    result = generate_video(product, with_music=not args.no_music)
    print(json.dumps(result, indent=2))
    if result.get("status") in ("completed", "completed_with_warnings"):
        print(f"\n[SUCCESS] Video ready: {result['video_path']}")
        sys.exit(0)
    else:
        print(f"\n[FAILED] Error: {result.get('error')}")
        sys.exit(1)


def cmd_submit(args):
    product = _load_product(args.json)
    product.mode = args.mode
    job_id = job_queue.submit(product)
    print(f"Queued job {job_id} for {product.name!r} in {product.mode} mode. "
          f"Queue depth: {job_queue.queue_depth()}")
    print(f"Check progress with: python cli.py status {job_id}")


def cmd_status(args):
    status = get_status(args.job_id)
    if not status:
        print("No such job.")
        sys.exit(1)
    print(json.dumps(status, indent=2))


def main():
    parser = argparse.ArgumentParser(description="FrameForge CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Render one video synchronously (no queue)")
    g.add_argument("mode", nargs="?", default="local", choices=["cloud", "local"], help="Rendering mode: 'cloud' or 'local'")
    g.add_argument("--json", required=True, help="Path to a product JSON file")
    g.add_argument("--no-music", action="store_true", help="Skip the ambient music bed")
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("submit", help="Enqueue a video job and return immediately")
    s.add_argument("mode", nargs="?", default="local", choices=["cloud", "local"], help="Rendering mode: 'cloud' or 'local'")
    s.add_argument("--json", required=True, help="Path to a product JSON file")
    s.set_defaults(func=cmd_submit)

    st = sub.add_parser("status", help="Check a job's status")
    st.add_argument("job_id")
    st.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
