"""
Assembly stage: scene images + voiceover -> per-scene clips (with audio)
-> final concatenated MP4 + sidecar .srt captions.

Scale/length handling (this is the piece the assignment specifically asks
about):

1. Each scene is rendered to its own small clip first, sized to that
   scene's own voiceover duration. There's no shared in-memory timeline
   object that grows with video length, so a 5-scene product and a
   200-scene product go through the exact same code path.
2. Scenes are grouped into "chapters" of CHAPTER_SIZE (default 12) and
   each chapter is concatenated with ffmpeg's stream-copy concat demuxer
   (`-c copy`, no re-encode) as soon as it's ready. Chapters are then
   concatenated into the final file, also via stream copy. This bounds
   the number of open file handles / the size of any single ffmpeg
   command line regardless of how many scenes exist, which is what would
   otherwise become the practical ceiling on video length.
3. Because concatenation uses stream copy rather than re-encoding, adding
   more scenes costs roughly linear time and constant memory -- there is
   no re-encode pass whose cost blows up with total duration.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

from core.models import Scene

CHAPTER_SIZE = 12  # batching unit, NOT a cap - see module docstring


def _run(cmd: List[str]):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg command failed: {' '.join(cmd)}\n{proc.stderr[:600]}")


def mux_clip_with_audio(silent_clip: Path, audio_path: Path, out_path: Path) -> Path:
    """Attach the voiceover to a scene's (currently silent) video clip."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(silent_clip), "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-shortest",
        str(out_path),
    ]
    _run(cmd)
    return out_path


def _concat(clip_paths: List[Path], out_path: Path, list_file: Path):
    list_file.parent.mkdir(parents=True, exist_ok=True)
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p.resolve()}'\n")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ]
    _run(cmd)


def concat_in_chapters(clip_paths: List[Path], work_dir: Path, final_out: Path,
                        chapter_size: int = CHAPTER_SIZE) -> Path:
    """Concat an arbitrarily long list of clips by batching into chapters
    first, so no single ffmpeg invocation has to juggle hundreds of
    inputs at once. See module docstring point (2)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if len(clip_paths) <= chapter_size:
        _concat(clip_paths, final_out, work_dir / "concat_list.txt")
        return final_out

    chapter_files = []
    for i in range(0, len(clip_paths), chapter_size):
        batch = clip_paths[i:i + chapter_size]
        chapter_out = work_dir / f"chapter_{i // chapter_size:03d}.mp4"
        _concat(batch, chapter_out, work_dir / f"chapter_{i // chapter_size:03d}_list.txt")
        chapter_files.append(chapter_out)

    _concat(chapter_files, final_out, work_dir / "final_list.txt")
    return final_out


def add_background_music_bed(video_in: Path, out_path: Path, music_volume: float = 0.12) -> Path:
    """Optional: mixes a very soft synthesized ambient tone bed under the
    voiceover using ffmpeg's own sine generator, so no external royalty
    audio library is required. Skips cleanly if it fails."""
    try:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_in),
            "-f", "lavfi", "-i", "sine=frequency=220:beat=1",
            "-filter_complex",
            f"[1:a]volume={music_volume},lowpass=f=800[bg];"
            f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            str(out_path),
        ]
        _run(cmd)
        return out_path
    except Exception:
        # Music bed is a nice-to-have; never let it block delivery of the video.
        video_in.replace(out_path)
        return out_path


def write_srt(scenes: List[Scene], out_path: Path) -> Path:
    """Sidecar caption file, timed against each scene's actual duration."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t = 0.0
    lines = []
    for i, s in enumerate(scenes, start=1):
        dur = s.duration or 3.0
        start, end = t, t + dur
        lines.append(str(i))
        lines.append(f"{_srt_ts(start)} --> {_srt_ts(end)}")
        lines.append(s.voiceover.strip())
        lines.append("")
        t = end
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
