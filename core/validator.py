"""
Quality validation module for generated marketing videos.

Called by pipeline.py after assembly to verify the output meets minimum
quality standards before marking a job as completed. This is a practical,
lightweight validator - it uses ffprobe to inspect the actual media
streams rather than just checking file size, which catches silent ffmpeg
failures (output file exists but contains zero-duration video, missing
audio track, etc.).

Design goals:
- Fast (< 1s extra per job using ffprobe metadata, no frame decoding)
- Non-invasive (validator failure degrades gracefully - the job is marked
  "completed_with_warnings" rather than "failed" so the video is still
  delivered)
- Extensible (ValidationResult carries a structured list of checks so
  callers can act on individual failures, not just a boolean)
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from core.models import Scene

logger = logging.getLogger(__name__)

# Minimum acceptable video duration in seconds.
# A valid marketing video should have at least a few seconds of content.
MIN_DURATION_SEC = 2.0

# Maximum tolerable fraction by which actual duration may differ from expected.
# e.g. 0.30 = allow ±30% drift (accounts for TTS timing variance).
DURATION_TOLERANCE = 0.30


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str


@dataclass
class ValidationResult:
    video_path: str
    passed: bool
    checks: List[CheckResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "passed": self.passed,
            "checks": [{"name": c.name, "passed": c.passed, "message": c.message}
                       for c in self.checks],
            "warnings": self.warnings,
        }


def validate_output(
    video_path: Path,
    scenes: Optional[List[Scene]] = None,
    srt_path: Optional[Path] = None,
) -> ValidationResult:
    """
    Run all quality checks against a finished video file.

    Args:
        video_path: Path to the final .mp4 output.
        scenes:     The list of Scene objects used to generate the video.
                    If provided, duration and scene count are cross-checked.
        srt_path:   Optional .srt caption file to check for presence.

    Returns:
        ValidationResult with per-check details and an overall passed flag.
    """
    result = ValidationResult(video_path=str(video_path), passed=True)

    # ── Check 1: Output file exists ──────────────────────────────────────────
    result.checks.append(_check_file_exists(video_path))

    if not video_path.exists():
        # All remaining checks require the file - short-circuit here.
        result.passed = False
        result.checks.append(CheckResult(
            "media_streams", False, "Skipped - file does not exist"))
        return result

    # ── Check 2: File is non-empty ────────────────────────────────────────────
    result.checks.append(_check_non_empty(video_path))

    # ── Probe the file once and reuse the data ────────────────────────────────
    probe = _ffprobe(video_path)

    # ── Check 3: Video stream present ─────────────────────────────────────────
    result.checks.append(_check_video_stream(probe))

    # ── Check 4: Audio stream present ─────────────────────────────────────────
    result.checks.append(_check_audio_stream(probe))

    # ── Check 5: Minimum duration ─────────────────────────────────────────────
    actual_duration = _get_duration(probe)
    result.checks.append(_check_min_duration(actual_duration))

    # ── Check 6: Expected duration (if scenes provided) ───────────────────────
    if scenes:
        expected_duration = sum(s.duration or 0 for s in scenes)
        result.checks.append(
            _check_expected_duration(actual_duration, expected_duration))

    # ── Check 7: Captions file present (if path provided) ─────────────────────
    if srt_path is not None:
        result.checks.append(_check_srt(srt_path))

    # ── Check 8: Scene count non-zero (if scenes provided) ────────────────────
    if scenes is not None:
        result.checks.append(_check_scene_count(scenes))

    # Aggregate: any hard failure → overall passed = False
    hard_failures = [c for c in result.checks if not c.passed]
    result.passed = len(hard_failures) == 0

    if not result.passed:
        result.warnings = [c.message for c in hard_failures]
        logger.warning("Validation FAILED for %s: %s", video_path, result.warnings)
    else:
        logger.info("Validation passed for %s (duration=%.1fs)", video_path, actual_duration)

    return result


# ── Individual check helpers ────────────────────────────────────────────────


def _check_file_exists(path: Path) -> CheckResult:
    if path.exists():
        return CheckResult("file_exists", True, f"Output file found at {path}")
    return CheckResult("file_exists", False, f"Output file not found: {path}")


def _check_non_empty(path: Path) -> CheckResult:
    size = path.stat().st_size
    if size > 1024:  # at least 1 KB - true empty would be bytes
        return CheckResult("file_non_empty", True, f"File size: {size:,} bytes")
    return CheckResult("file_non_empty", False,
                       f"File suspiciously small: {size} bytes (possible silent failure)")


def _check_video_stream(probe: Optional[dict]) -> CheckResult:
    if probe is None:
        return CheckResult("video_stream", False, "ffprobe failed - cannot inspect streams")
    streams = probe.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    if video_streams:
        s = video_streams[0]
        codec = s.get("codec_name", "unknown")
        w = s.get("width", "?")
        h = s.get("height", "?")
        return CheckResult("video_stream", True,
                           f"Video stream: {codec} {w}x{h}")
    return CheckResult("video_stream", False, "No video stream found in output file")


def _check_audio_stream(probe: Optional[dict]) -> CheckResult:
    if probe is None:
        return CheckResult("audio_stream", False, "ffprobe failed - cannot inspect streams")
    streams = probe.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if audio_streams:
        s = audio_streams[0]
        codec = s.get("codec_name", "unknown")
        rate = s.get("sample_rate", "?")
        return CheckResult("audio_stream", True,
                           f"Audio stream: {codec} @ {rate}Hz")
    return CheckResult("audio_stream", False,
                       "No audio stream found - voiceover may be missing")


def _check_min_duration(actual_sec: float) -> CheckResult:
    if actual_sec >= MIN_DURATION_SEC:
        return CheckResult("min_duration", True,
                           f"Duration {actual_sec:.2f}s ≥ minimum {MIN_DURATION_SEC}s")
    return CheckResult("min_duration", False,
                       f"Duration {actual_sec:.2f}s is below minimum {MIN_DURATION_SEC}s")


def _check_expected_duration(actual_sec: float, expected_sec: float) -> CheckResult:
    if expected_sec <= 0:
        return CheckResult("expected_duration", True, "No expected duration to compare")
    diff = abs(actual_sec - expected_sec) / max(expected_sec, 1.0)
    if diff <= DURATION_TOLERANCE:
        return CheckResult("expected_duration", True,
                           f"Duration {actual_sec:.2f}s within {DURATION_TOLERANCE*100:.0f}% "
                           f"of expected {expected_sec:.2f}s")
    return CheckResult("expected_duration", False,
                       f"Duration mismatch: actual={actual_sec:.2f}s, "
                       f"expected={expected_sec:.2f}s, drift={diff*100:.1f}%")


def _check_srt(path: Path) -> CheckResult:
    if path.exists() and path.stat().st_size > 0:
        return CheckResult("captions_file", True, f"Captions file found: {path}")
    return CheckResult("captions_file", False,
                       f"Captions file missing or empty: {path}")


def _check_scene_count(scenes: List[Scene]) -> CheckResult:
    n = len(scenes)
    if n > 0:
        return CheckResult("scene_count", True, f"{n} scenes generated")
    return CheckResult("scene_count", False,
                       "Scene list is empty - script generation may have failed silently")


# ── ffprobe helpers ──────────────────────────────────────────────────────────


def _ffprobe(path: Path) -> Optional[dict]:
    """Run ffprobe on path and return parsed JSON, or None on failure."""
    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            logger.debug("ffprobe returned %d: %s", proc.returncode, proc.stderr[:200])
            return None
        return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        logger.debug("ffprobe probe failed: %s", exc)
        return None


def _get_duration(probe: Optional[dict]) -> float:
    """Extract duration in seconds from an ffprobe result dict."""
    if probe is None:
        return 0.0

    # Try format-level duration first
    fmt = probe.get("format", {})
    raw = fmt.get("duration", "")
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    # Fall back to the first stream that has a duration tag
    for stream in probe.get("streams", []):
        raw = stream.get("duration", "")
        if raw:
            try:
                val = float(raw)
                if val > 0:
                    return val
            except (ValueError, TypeError):
                continue

    return 0.0
