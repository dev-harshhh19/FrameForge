"""
Text-to-speech provider abstraction.

Why an abstraction at all: the assignment explicitly asks the design to
avoid being capped by any single provider's rate limits / quotas. The way
this project does that for voice is a provider *chain*: try a cloud TTS
provider first (better voices), and if it is rate-limited, errors, or is
simply not configured (no API key / no network, as in this sandbox),
fall back to a fully local, offline engine that never runs out of quota
because it isn't calling anyone.

Local default: ffmpeg's built-in `flite` libavfilter source
(`-f lavfi -i "flite=text='...':voice=slt"`). This ships with ffmpeg on
this system (compiled --enable-libflite) and requires no network, no API
key, and no extra Python deps -- which is what makes the "no hard cap on
generation frequency" claim concrete rather than aspirational: nothing
external can throttle it.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


class TTSError(Exception):
    pass


@dataclass
class TTSResult:
    audio_path: Path
    duration_sec: float


class TTSProvider:
    name = "base"

    def synthesize(self, text: str, out_path: Path, voice: str = "slt") -> TTSResult:
        raise NotImplementedError


class FliteLocalTTSProvider(TTSProvider):
    """Offline TTS via ffmpeg's libflite filter. No network, no cap."""

    name = "flite-local"
    # ffmpeg/flite ships a handful of built-in voices; anything unknown
    # silently falls back to 'kal16' inside flite itself.
    VOICES = {"slt", "kal", "kal16", "awb", "rms"}

    def synthesize(self, text: str, out_path: Path, voice: str = "slt") -> TTSResult:
        voice = voice if voice in self.VOICES else "slt"
        text = text.replace("\n", " ").strip() or "..."
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Use `textfile` rather than the inline `text` option: flite's inline
        # option is parsed as part of ffmpeg's filtergraph mini-language, so
        # commas/colons/quotes in normal marketing copy break the parser.
        # A textfile sidesteps escaping entirely.
        textfile = out_path.with_suffix(".txt")
        textfile.write_text(text, encoding="utf-8")
        import os
        textfile_str = os.path.relpath(textfile).replace('\\', '/')
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"flite=textfile={textfile_str}:voice={voice}",
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out_path.exists():
            raise TTSError(f"flite synthesis failed: {proc.stderr[:400]}")
        return TTSResult(audio_path=out_path, duration_sec=_probe_duration(out_path))


class GeminiTTSProvider(TTSProvider):
    """
    Cloud TTS via Gemini 2.5 Flash Preview TTS.
    Uses GOOGLE_API_KEY from .env. Falls back gracefully on failure.
    """

    name = "gemini-cloud"

    # Valid Gemini TTS prebuilt voice names
    GEMINI_VOICES = {"Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"}

    def __init__(self, api_key: Optional[str] = None):
        import os
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")

    def synthesize(self, text: str, out_path: Path, voice: str = "Kore") -> TTSResult:
        if not self.api_key:
            raise TTSError("GOOGLE_API_KEY not set - cannot use cloud TTS")

        # Map unknown voice strings to a valid Gemini voice
        if voice not in self.GEMINI_VOICES:
            voice = "Kore"

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise TTSError("google-genai package not installed. Run: pip install google-genai")

        print(f"[Cloud TTS] Calling Gemini TTS (voice={voice})...")

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice,
                        )
                    )
                ),
            ),
        )

        audio_data = response.candidates[0].content.parts[0].inline_data.data
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Gemini returns raw PCM; write to a temp file then convert to WAV
        raw_path = out_path.with_suffix(".raw")
        raw_path.write_bytes(audio_data)

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", "24000", "-ac", "1",
            "-i", str(raw_path),
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        raw_path.unlink(missing_ok=True)

        if proc.returncode != 0 or not out_path.exists():
            raise TTSError(f"ffmpeg PCM->WAV conversion failed: {proc.stderr[:400]}")

        duration = _probe_duration(out_path)
        print(f"[Cloud TTS] Success. Duration: {duration:.1f}s")
        return TTSResult(audio_path=out_path, duration_sec=duration)


# Keep the old name as an alias so existing imports don't break
CloudTTSProviderStub = GeminiTTSProvider



class TTSPipeline:
    """
    Wraps a provider chain with retry/backoff so a transient rate-limit or
    network error doesn't kill a whole video render -- it just falls
    through to the next provider in `providers`.
    """

    def __init__(self, providers: Optional[List[TTSProvider]] = None,
                 max_retries: int = 2, backoff_base: float = 0.6):
        self.providers = providers or [CloudTTSProviderStub(), FliteLocalTTSProvider()]
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def synthesize(self, text: str, out_path: Path, voice: str = "slt") -> TTSResult:
        last_err: Optional[Exception] = None
        for provider in self.providers:
            for attempt in range(self.max_retries + 1):
                try:
                    return provider.synthesize(text, out_path, voice=voice)
                except Exception as e:  # noqa: BLE001 - want to try next provider
                    last_err = e
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_base * (2 ** attempt))
            # exhausted retries on this provider -> fall through to next one
        raise TTSError(f"all TTS providers failed: {last_err}")


def _probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return max(float(proc.stdout.strip()), 0.8)
    except ValueError:
        return 2.5
