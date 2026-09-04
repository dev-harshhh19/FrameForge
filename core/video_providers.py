"""
Turns one Scene (heading/body + a still image + a voiceover track) into a
short video clip. Same provider-chain idea as tts_providers.py: a cloud
text-to-video model (Runway Gen-3, Pika, Luma, Sora, etc.) is a drop-in
alternative to the local renderer, selected per job or with automatic
fallback if the cloud call fails or is rate-limited.

Local default: ffmpeg `zoompan` filter for a subtle Ken Burns effect on
the Pillow-rendered slide, timed to match the voiceover duration exactly
(no fixed per-scene length -- long voiceover -> longer clip, short
voiceover -> shorter clip). This is the piece of the design that removes
any hard cap on total video length: total length = sum of scene
durations, and scene duration is derived from the script, not a config
constant.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


class VideoProviderError(Exception):
    pass


class VideoClipProvider:
    name = "base"

    def render_clip(self, image_path: Path, duration_sec: float, out_path: Path,
                     fps: int = 30) -> Path:
        raise NotImplementedError


class LocalKenBurnsProvider(VideoClipProvider):
    """Offline: image -> slow zoom/pan video clip via ffmpeg zoompan. No API, no cap."""

    name = "local-kenburns"

    def render_clip(self, image_path: Path, duration_sec: float, out_path: Path,
                     fps: int = 30) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frames = max(int(round(duration_sec * fps)), fps)  # at least 1s
        zoom_expr = "min(zoom+0.0006,1.08)"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-i", str(image_path),
            "-vf",
            f"scale=1920:1080,zoompan=z='{zoom_expr}':d={frames}:s=1920x1080:fps={fps},"
            f"format=yuv420p",
            "-t", f"{duration_sec:.3f}",
            "-r", str(fps),
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out_path.exists():
            raise VideoProviderError(f"local render failed: {proc.stderr[:400]}")
        return out_path


class CloudTextToVideoProviderStub(VideoClipProvider):
    """
    Placeholder for a real text-to-video API. Wire up `_call_api` with the
    provider's SDK/HTTP call. Kept separate from the local renderer so the
    pipeline can try it first for higher-fidelity generative shots and
    silently fall back to LocalKenBurnsProvider on error/HTTP 429/timeout
    (see VideoRenderPipeline below) instead of failing the whole job.
    """

    name = "cloud-stub"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def render_clip(self, image_path: Path, duration_sec: float, out_path: Path,
                     fps: int = 30) -> Path:
        if not self.api_key:
            raise VideoProviderError("cloud text-to-video not configured - fallback expected")
        raise VideoProviderError("cloud text-to-video call not implemented in this stub")


class VideoRenderPipeline:
    """Provider chain with fallback, mirroring TTSPipeline."""

    def __init__(self, providers=None):
        self.providers = providers or [CloudTextToVideoProviderStub(), LocalKenBurnsProvider()]

    def render_clip(self, image_path: Path, duration_sec: float, out_path: Path,
                     fps: int = 30) -> Path:
        last_err = None
        for provider in self.providers:
            try:
                return provider.render_clip(image_path, duration_sec, out_path, fps=fps)
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        raise VideoProviderError(f"all video providers failed: {last_err}")
