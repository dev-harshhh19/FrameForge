"""
Data model for the input the bot accepts.

Deliberately loose / data-driven: nothing downstream reads a fixed number
of "features" or a fixed "duration" from here. Whatever the caller sends
is what gets turned into scenes later (see script_generator.py), which is
the mechanism that lets the pipeline scale to any length without a
hardcoded cap.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


def _slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return text or "product"


@dataclass
class ProductInput:
    name: str
    description: str
    features: List[str] = field(default_factory=list)
    target_audience: str = ""
    call_to_action: str = "Learn more today."
    brand_color: str = "#1D4ED8"          # hex, used for on-brand visuals
    logo_path: Optional[str] = None        # path to an uploaded logo/image
    image_paths: List[str] = field(default_factory=list)  # extra product images
    voice: str = "slt"                     # flite voice (see tts_providers.py)
    tone: str = "energetic"                # energetic | professional | calm
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    notify_webhook: Optional[str] = None   # where to "deliver" the finished video
    notify_email: Optional[str] = None
    mode: str = "local"                    # 'local' or 'cloud'

    @property
    def slug(self) -> str:
        return _slugify(self.name)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ProductInput":
        allowed = {f for f in ProductInput.__dataclass_fields__.keys()}
        clean = {k: v for k, v in d.items() if k in allowed and v not in (None, "")}
        # features may arrive as a newline/comma separated string from a web form
        feats = clean.get("features")
        if isinstance(feats, str):
            parts = re.split(r"[\n,]", feats)
            clean["features"] = [p.strip() for p in parts if p.strip()]
        imgs = clean.get("image_paths")
        if isinstance(imgs, str):
            clean["image_paths"] = [p.strip() for p in imgs.split(",") if p.strip()]
        return ProductInput(**clean)


@dataclass
class Scene:
    """One beat of the video. A storyboard is just a list of these -
    there is no maximum list length anywhere in the code."""
    index: int
    kind: str           # "intro" | "feature" | "audience" | "cta"
    heading: str
    body: str
    voiceover: str
    image_path: Optional[str] = None
    duration: Optional[float] = None  # filled in once the VO audio is rendered
