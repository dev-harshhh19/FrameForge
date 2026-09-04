"""
Tests for core/validator.py - the quality validation module.

Covers:
  - Missing file detection
  - Empty / tiny file detection
  - Stream parsing from ffprobe output
  - Duration checks (minimum, expected with tolerance)
  - SRT file presence check
  - Scene count check
  - Full ValidationResult structure
  - Graceful handling of ffprobe unavailability
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.validator import (
    ValidationResult, CheckResult,
    validate_output,
    _check_file_exists,
    _check_non_empty,
    _check_min_duration,
    _check_expected_duration,
    _check_audio_stream,
    _check_video_stream,
    _check_srt,
    _check_scene_count,
    _get_duration,
    MIN_DURATION_SEC,
    DURATION_TOLERANCE,
)
from core.models import Scene


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_probe(duration: float = 30.0,
                has_video: bool = True,
                has_audio: bool = True) -> dict:
    """Build a minimal ffprobe-style JSON dict."""
    streams = []
    if has_video:
        streams.append({
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
        })
    if has_audio:
        streams.append({
            "codec_type": "audio",
            "codec_name": "aac",
            "sample_rate": "44100",
        })
    return {
        "streams": streams,
        "format": {"duration": str(duration)},
    }


def _make_scene(index: int, duration: float = 3.0) -> Scene:
    return Scene(
        index=index, kind="feature",
        heading=f"H{index}", body=f"B{index}",
        voiceover=f"Voiceover {index}.",
        duration=duration,
    )


# ── 1. Individual check helpers ───────────────────────────────────────────────

class TestCheckFileExists(unittest.TestCase):

    def test_file_exists_pass(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            c = _check_file_exists(Path(f.name))
            self.assertTrue(c.passed)

    def test_file_missing_fail(self):
        c = _check_file_exists(Path("/tmp/nonexistent_xyz_abc.mp4"))
        self.assertFalse(c.passed)
        self.assertIn("not found", c.message)


class TestCheckNonEmpty(unittest.TestCase):

    def test_large_file_pass(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x" * 2048)
            f.flush()
            c = _check_non_empty(Path(f.name))
            self.assertTrue(c.passed)

    def test_tiny_file_fail(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"tiny")
            f.flush()
            c = _check_non_empty(Path(f.name))
            self.assertFalse(c.passed)
            self.assertIn("small", c.message)


class TestCheckVideoStream(unittest.TestCase):

    def test_has_video_pass(self):
        probe = _fake_probe(has_video=True)
        c = _check_video_stream(probe)
        self.assertTrue(c.passed)
        self.assertIn("h264", c.message)

    def test_no_video_fail(self):
        probe = _fake_probe(has_video=False)
        c = _check_video_stream(probe)
        self.assertFalse(c.passed)

    def test_none_probe_fail(self):
        c = _check_video_stream(None)
        self.assertFalse(c.passed)


class TestCheckAudioStream(unittest.TestCase):

    def test_has_audio_pass(self):
        probe = _fake_probe(has_audio=True)
        c = _check_audio_stream(probe)
        self.assertTrue(c.passed)
        self.assertIn("aac", c.message)

    def test_no_audio_fail(self):
        probe = _fake_probe(has_audio=False)
        c = _check_audio_stream(probe)
        self.assertFalse(c.passed)
        self.assertIn("missing", c.message.lower())


class TestCheckMinDuration(unittest.TestCase):

    def test_above_minimum_pass(self):
        c = _check_min_duration(MIN_DURATION_SEC + 1.0)
        self.assertTrue(c.passed)

    def test_exactly_minimum_pass(self):
        c = _check_min_duration(MIN_DURATION_SEC)
        self.assertTrue(c.passed)

    def test_below_minimum_fail(self):
        c = _check_min_duration(MIN_DURATION_SEC - 0.5)
        self.assertFalse(c.passed)


class TestCheckExpectedDuration(unittest.TestCase):

    def test_within_tolerance_pass(self):
        expected = 30.0
        actual = expected * (1 + DURATION_TOLERANCE * 0.5)  # half the tolerance
        c = _check_expected_duration(actual, expected)
        self.assertTrue(c.passed)

    def test_exact_match_pass(self):
        c = _check_expected_duration(30.0, 30.0)
        self.assertTrue(c.passed)

    def test_outside_tolerance_fail(self):
        expected = 30.0
        actual = expected * (1 + DURATION_TOLERANCE + 0.1)  # over tolerance
        c = _check_expected_duration(actual, expected)
        self.assertFalse(c.passed)
        self.assertIn("mismatch", c.message)

    def test_zero_expected_always_pass(self):
        """If no expected duration, the check should pass unconditionally."""
        c = _check_expected_duration(0.0, 0.0)
        self.assertTrue(c.passed)


class TestCheckSrt(unittest.TestCase):

    def test_srt_present_pass(self):
        with tempfile.NamedTemporaryFile(suffix=".srt", mode="w", delete=False) as f:
            f.write("1\n00:00:00,000 --> 00:00:03,000\nHello\n")
            p = Path(f.name)
        try:
            c = _check_srt(p)
            self.assertTrue(c.passed)
        finally:
            p.unlink(missing_ok=True)

    def test_srt_missing_fail(self):
        c = _check_srt(Path("/tmp/nonexistent_xyz.srt"))
        self.assertFalse(c.passed)


class TestCheckSceneCount(unittest.TestCase):

    def test_nonempty_pass(self):
        c = _check_scene_count([_make_scene(0), _make_scene(1)])
        self.assertTrue(c.passed)

    def test_empty_fail(self):
        c = _check_scene_count([])
        self.assertFalse(c.passed)


# ── 2. Duration extraction ────────────────────────────────────────────────────

class TestGetDuration(unittest.TestCase):

    def test_from_format(self):
        probe = {"format": {"duration": "42.5"}, "streams": []}
        self.assertAlmostEqual(_get_duration(probe), 42.5)

    def test_from_stream_fallback(self):
        probe = {
            "format": {},
            "streams": [{"codec_type": "video", "duration": "15.0"}],
        }
        self.assertAlmostEqual(_get_duration(probe), 15.0)

    def test_none_probe(self):
        self.assertEqual(_get_duration(None), 0.0)

    def test_malformed_duration(self):
        probe = {"format": {"duration": "not-a-number"}, "streams": []}
        self.assertEqual(_get_duration(probe), 0.0)


# ── 3. Full validate_output function ─────────────────────────────────────────

class TestValidateOutput(unittest.TestCase):

    def test_missing_file_fails(self):
        result = validate_output(Path("/tmp/does_not_exist_xyz.mp4"))
        self.assertFalse(result.passed)
        self.assertIn("file_exists", {c.name for c in result.checks})
        file_check = next(c for c in result.checks if c.name == "file_exists")
        self.assertFalse(file_check.passed)

    def test_tiny_file_fails(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"small")
            f.flush()
            # _ffprobe will fail on a fake file - validation should still
            # catch the non-empty check failure
            with patch("core.validator._ffprobe", return_value=None):
                result = validate_output(Path(f.name))
        # file exists but non_empty check should fail
        non_empty = next(c for c in result.checks if c.name == "file_non_empty")
        self.assertFalse(non_empty.passed)
        self.assertFalse(result.passed)

    def test_good_file_passes(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x" * 10000)
            f.flush()
            probe = _fake_probe(duration=30.0, has_video=True, has_audio=True)
            with patch("core.validator._ffprobe", return_value=probe):
                result = validate_output(Path(f.name))
        self.assertTrue(result.passed, msg=str(result.warnings))

    def test_no_audio_fails(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x" * 10000)
            f.flush()
            probe = _fake_probe(duration=30.0, has_video=True, has_audio=False)
            with patch("core.validator._ffprobe", return_value=probe):
                result = validate_output(Path(f.name))
        self.assertFalse(result.passed)
        audio_check = next(c for c in result.checks if c.name == "audio_stream")
        self.assertFalse(audio_check.passed)

    def test_scene_list_passed_through(self):
        scenes = [_make_scene(i, duration=5.0) for i in range(3)]
        expected_total = 15.0
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x" * 10000)
            f.flush()
            probe = _fake_probe(
                duration=expected_total,
                has_video=True, has_audio=True,
            )
            with patch("core.validator._ffprobe", return_value=probe):
                result = validate_output(Path(f.name), scenes=scenes)
        self.assertTrue(result.passed)
        scene_check = next(c for c in result.checks if c.name == "scene_count")
        self.assertTrue(scene_check.passed)
        self.assertIn("3", scene_check.message)

    def test_validation_result_to_dict(self):
        r = ValidationResult(
            video_path="/tmp/test.mp4",
            passed=True,
            checks=[CheckResult("file_exists", True, "Found")],
        )
        d = r.to_dict()
        self.assertEqual(d["video_path"], "/tmp/test.mp4")
        self.assertTrue(d["passed"])
        self.assertEqual(len(d["checks"]), 1)
        self.assertEqual(d["checks"][0]["name"], "file_exists")

    def test_srt_path_checked_when_provided(self):
        with tempfile.TemporaryDirectory() as td:
            mp4 = Path(td) / "video.mp4"
            mp4.write_bytes(b"x" * 10000)
            srt = Path(td) / "video.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:03,000\nHello\n")
            probe = _fake_probe(duration=20.0)
            with patch("core.validator._ffprobe", return_value=probe):
                result = validate_output(mp4, srt_path=srt)
        srt_check = next(c for c in result.checks if c.name == "captions_file")
        self.assertTrue(srt_check.passed)


# ── 4. Edge cases ─────────────────────────────────────────────────────────────

class TestValidatorEdgeCases(unittest.TestCase):

    def test_ffprobe_unavailable_graceful(self):
        """If ffprobe is not on PATH, validation should degrade gracefully."""
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x" * 5000)
            f.flush()
            # Simulate ffprobe not found
            with patch("core.validator._ffprobe", return_value=None):
                result = validate_output(Path(f.name))
        # video/audio stream checks will fail, but no exception raised
        self.assertIsInstance(result, ValidationResult)

    def test_multiple_failed_checks_all_in_warnings(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(b"x" * 5000)
            f.flush()
            probe = _fake_probe(duration=30.0, has_video=False, has_audio=False)
            with patch("core.validator._ffprobe", return_value=probe):
                result = validate_output(Path(f.name))
        self.assertFalse(result.passed)
        self.assertGreater(len(result.warnings), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
