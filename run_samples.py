#!/usr/bin/env python3
"""
End-to-end test across every sample product. Renders each one
synchronously with generate_video() (the exact function the queue workers
call) and prints a pass/fail summary. This is the "test with 2-3 sample
products" deliverable.

Usage: python run_samples.py
"""
import json
import time
from pathlib import Path

from core.models import ProductInput
from core.pipeline import generate_video

SAMPLES = sorted(Path("samples").glob("*.json"))


def main():
    print(f"Found {len(SAMPLES)} sample products.\n")
    results = []
    for sample_path in SAMPLES:
        data = json.loads(sample_path.read_text())
        product = ProductInput.from_dict(data)
        print(f"-> Rendering {product.name!r} ({len(product.features)} features)...")
        t0 = time.time()
        result = generate_video(product)
        elapsed = time.time() - t0
        ok = result.get("status") in ("completed", "completed_with_warnings")
        results.append((product.name, ok, elapsed, result))
        if ok:
            print(f"  [SUCCESS] done in {elapsed:.1f}s -> {result['video_path']} "
                  f"({result['scene_count']} scenes, {result['duration_sec']:.1f}s runtime)\n")
        else:
            print(f"  [FAILED] FAILED after {elapsed:.1f}s: {result.get('error')}\n")

    print("=" * 60)
    print("SUMMARY")
    for name, ok, elapsed, result in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name} ({elapsed:.1f}s)")
    n_pass = sum(1 for _, ok, _, _ in results if ok)
    print(f"\n{n_pass}/{len(results)} sample products rendered successfully.")


if __name__ == "__main__":
    main()
