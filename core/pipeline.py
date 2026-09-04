"""
End-to-end orchestration for turning one ProductInput into one finished
marketing video. This is the function a queue worker calls per job.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from core.models import ProductInput
from core.script_generator import TemplateScriptGenerator
from core.tts_providers import TTSPipeline, CloudTTSProviderStub, FliteLocalTTSProvider, ElevenLabsTTSProvider
from core.video_providers import VideoRenderPipeline
from core.scene_renderer import render_scene_image, render_scene_image_cloud
from core.assembler import (
    mux_clip_with_audio, concat_in_chapters, add_background_music_bed,
    write_srt,
)
from core.notify import notify

OUTPUT_DIR = Path("outputs")
JOBS_DIR = Path("jobs")
WORK_ROOT = Path("work")


def _update_status(job_id: str, **fields):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    path = JOBS_DIR / f"{job_id}.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}
    data.update(fields)
    data["job_id"] = job_id
    data["updated_at"] = time.time()
    path.write_text(json.dumps(data, indent=2))
    return data


def get_status(job_id: str) -> Optional[dict]:
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def generate_video(product: ProductInput, with_music: bool = True) -> dict:
    """Runs the whole pipeline synchronously and returns a status dict.
    Called by both the queue worker (async use) and the CLI (direct use)."""
    job_id = product.job_id
    work_dir = WORK_ROOT / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        _update_status(job_id, status="scripting", product=product.to_dict())
        print(f"[Pipeline] mode={product.mode}, voice={product.voice}")

        scenes = TemplateScriptGenerator().generate(product)
        
        # Select TTS providers based on mode
        # Cloud mode: TTS stays cloud-only (no local fallback for voice quality)
        # Image gen already has its own local Pillow fallback in render_scene_image_cloud()
        if product.mode == "cloud":
            import os
            providers = []
            
            # 1. Collect all GOOGLE_API_KEY* env vars
            google_keys = []
            if os.environ.get("GOOGLE_API_KEY"):
                google_keys.append(os.environ.get("GOOGLE_API_KEY"))
            for k, v in os.environ.items():
                if k.startswith("GOOGLE_API_KEY_") and v and v not in google_keys:
                    google_keys.append(v)
            
            # Add a Gemini provider for each Google key
            for key in google_keys:
                providers.append(CloudTTSProviderStub(api_key=key))
                
            # 2. Add ElevenLabs fallback if key exists
            if os.environ.get("ELEVENLABS_API_KEY"):
                providers.append(ElevenLabsTTSProvider(api_key=os.environ.get("ELEVENLABS_API_KEY")))
                
            # 3. Fallback to a stub if no keys were found to throw a proper error
            if not providers:
                providers = [CloudTTSProviderStub()]
            
            tts = TTSPipeline(providers=providers, max_retries=0)
        else:
            providers = [FliteLocalTTSProvider()]
            tts = TTSPipeline(providers=providers)
        
        video_provider = VideoRenderPipeline()

        _update_status(job_id, status="rendering_scenes", total_scenes=len(scenes))

        muxed_clips = []
        for scene in scenes:
            # 1) voiceover audio, duration-accurate
            audio_path = work_dir / f"scene_{scene.index:03d}.wav"
            tts_result = tts.synthesize(scene.voiceover, audio_path, voice=product.voice)
            scene.duration = tts_result.duration_sec

            # 2) on-brand slide image for this scene
            image_path = work_dir / f"scene_{scene.index:03d}.png"
            product_image = None
            if scene.kind == "intro" and product.image_paths:
                product_image = product.image_paths[0]
            
            render_scene_image(
                heading=scene.heading, body=scene.body, kind=scene.kind,
                out_path=image_path, brand_color=product.brand_color,
                logo_path=product.logo_path, product_image_path=product_image,
            )
            scene.image_path = str(image_path)

            # 3) silent video clip timed to the voiceover, then mux audio in
            silent_clip = work_dir / f"clip_silent_{scene.index:03d}.mp4"
            video_provider.render_clip(Path(image_path), scene.duration, silent_clip)

            final_clip = work_dir / f"clip_{scene.index:03d}.mp4"
            mux_clip_with_audio(silent_clip, audio_path, final_clip)
            muxed_clips.append(final_clip)

            _update_status(job_id, status="rendering_scenes",
                            scenes_done=scene.index + 1, total_scenes=len(scenes))

        _update_status(job_id, status="assembling")
        raw_concat = work_dir / "concat_raw.mp4"
        concat_in_chapters(muxed_clips, work_dir / "chapters", raw_concat)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        final_path = OUTPUT_DIR / f"{product.slug}_{job_id}.mp4"

        if with_music:
            add_background_music_bed(raw_concat, final_path)
        else:
            shutil.copy(raw_concat, final_path)

        srt_path = OUTPUT_DIR / f"{product.slug}_{job_id}.srt"
        write_srt(scenes, srt_path)

        _update_status(job_id, status="delivering")
        delivery = notify(job_id, final_path, srt_path,
                           webhook_url=product.notify_webhook, email=product.notify_email)

        result = _update_status(
            job_id, status="completed",
            video_path=str(final_path), captions_path=str(srt_path),
            duration_sec=sum(s.duration or 0 for s in scenes),
            scene_count=len(scenes), delivery=delivery,
        )
        return result

    except Exception as e:  # noqa: BLE001
        return _update_status(job_id, status="failed", error=str(e))
    finally:
        # keep intermediate scene assets out of the repo's working tree size;
        # comment out during debugging if you want to inspect per-scene clips
        shutil.rmtree(work_dir, ignore_errors=True)
