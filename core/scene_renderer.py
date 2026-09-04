"""
Renders each Scene into a 1920x1080 PNG "slide" using Pillow.

This is the local, always-available visual layer: no text-to-video API is
required to get a coherent, on-brand video. A cloud text-to-video provider
(Runway, Pika, Luma, etc.) can be dropped in as an alternative
`SceneImageProvider` (see VideoClipProvider stubs in video_providers.py)
for photoreal/animated shots; the assembler downstream doesn't care which
one produced the frame as long as it gets an image or short clip back.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
import sys
if sys.platform == "win32":
    FONT_DIR = "C:/Windows/Fonts"
    HEADING_FONT = f"{FONT_DIR}/arialbd.ttf"
    BODY_FONT = f"{FONT_DIR}/arial.ttf"
    KICKER_FONT = f"{FONT_DIR}/courbd.ttf"
else:
    FONT_DIR = "/usr/share/fonts/truetype"
    HEADING_FONT = f"{FONT_DIR}/dejavu/DejaVuSans-Bold.ttf"
    BODY_FONT = f"{FONT_DIR}/dejavu/DejaVuSans.ttf"
    KICKER_FONT = f"{FONT_DIR}/dejavu/DejaVuSansMono.ttf"


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) != 6:
        h = "5B4CFF"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient_bg(brand_color: str) -> Image.Image:
    top = _hex_to_rgb(brand_color)
    bottom = _lerp(top, (10, 10, 20), 0.75)
    img = Image.new("RGB", (W, H), top)
    px = img.load()
    for y in range(H):
        t = y / H
        r, g, b = _lerp(top, bottom, t)
        for x in range(0, W, 4):  # step for speed, fine for a soft gradient
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = (r, g, b)
    return img.filter(ImageFilter.GaussianBlur(0.5))


def _fit_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _wrap_to_width(draw: ImageDraw.ImageDraw, text: str, font, max_width: int):
    words = text.replace("\n", " ").split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_scene_image(
    heading: str,
    body: str,
    kind: str,
    out_path: Path,
    brand_color: str = "#1D4ED8",
    kicker: Optional[str] = None,
    logo_path: Optional[str] = None,
    product_image_path: Optional[str] = None,
) -> Path:
    img = _gradient_bg(brand_color)
    draw = ImageDraw.Draw(img)

    margin = 130
    content_right = W - margin

    # Optional product/inset image on the right third of the frame.
    text_max_width = W - 2 * margin
    if product_image_path and Path(product_image_path).exists():
        try:
            inset = Image.open(product_image_path).convert("RGBA")
            target_h = int(H * 0.55)
            ratio = target_h / inset.height
            inset = inset.resize((max(1, int(inset.width * ratio)), target_h))
            ix = W - inset.width - 90
            iy = (H - inset.height) // 2
            # soft card behind the image
            card = Image.new("RGBA", (inset.width + 40, inset.height + 40), (255, 255, 255, 40))
            img.paste(card, (ix - 20, iy - 20), card)
            img.paste(inset, (ix, iy), inset)
            text_max_width = ix - margin - 60
            content_right = ix - 60
        except Exception:
            pass

    # Kicker (small label above heading)
    kicker_text = kicker or {"intro": "NEW", "feature": "FEATURE",
                              "audience": "WHO IT'S FOR", "cta": "GET STARTED"}.get(kind, "")
    y = int(H * 0.28)
    if kicker_text:
        kf = _fit_font(KICKER_FONT, 34)
        draw.text((margin, y), kicker_text.upper(), font=kf, fill=(255, 255, 255, 220))
        y += 60

    # Heading
    hf_size = 96 if kind == "intro" else 74
    hf = _fit_font(HEADING_FONT, hf_size)
    heading_lines = _wrap_to_width(draw, heading, hf, text_max_width)[:3]
    for line in heading_lines:
        draw.text((margin, y), line, font=hf, fill="white")
        y += int(hf_size * 1.15)

    y += 30
    bf = _fit_font(BODY_FONT, 42)
    body_lines = _wrap_to_width(draw, body, bf, text_max_width)[:6]
    for line in body_lines:
        draw.text((margin, y), line, font=bf, fill=(235, 235, 245))
        y += 58

    # Logo, bottom-left
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            target_h = 90
            ratio = target_h / logo.height
            logo = logo.resize((max(1, int(logo.width * ratio)), target_h))
            img.paste(logo, (margin, H - 150), logo)
        except Exception:
            pass

    # Thin accent bar bottom
    draw.rectangle([(0, H - 14), (W, H)], fill=_hex_to_rgb(brand_color))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, quality=95)
    return out_path


def render_scene_image_cloud(
    heading: str,
    body: str,
    kind: str,
    out_path: Path,
    brand_color: str = "#1D4ED8",
    kicker: Optional[str] = None,
    logo_path: Optional[str] = None,
    product_image_path: Optional[str] = None,
    product_name: str = "",
) -> Path:
    """Generate a scene image using Gemini Imagen, with local Pillow fallback."""
    import os
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[Cloud Visual] No GOOGLE_API_KEY, falling back to local renderer.")
        return render_scene_image(
            heading=heading, body=body, kind=kind, out_path=out_path,
            brand_color=brand_color, kicker=kicker, logo_path=logo_path,
            product_image_path=product_image_path,
        )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        scene_desc = {
            "intro": f"a cinematic wide-angle product shot of {product_name}",
            "feature": f"a detailed close-up highlighting: {heading}",
            "audience": f"a lifestyle scene showing the target audience using {product_name}",
            "cta": f"a bold call-to-action scene for {product_name} with dramatic lighting",
        }
        base_prompt = scene_desc.get(kind, f"a professional marketing scene for {product_name}")
        prompt = (
            f"Create a photorealistic 1920x1080 marketing image. "
            f"{base_prompt}. "
            f"Text overlay: \"{heading}\". "
            f"Brand color: {brand_color}. "
            f"Style: cinematic, high production value, no watermarks."
        )

        print(f"[Cloud Visual] Generating image for scene: {kind}...")
        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
            ),
        )

        if response.generated_images and len(response.generated_images) > 0:
            img_bytes = response.generated_images[0].image.image_bytes
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(img_bytes)
            print(f"[Cloud Visual] Success for {kind} scene.")
            return out_path

        raise Exception("No image returned from Gemini Imagen")

    except Exception as e:
        print(f"[Cloud Visual] Gemini image generation failed ({e}), using local renderer.")
        return render_scene_image(
            heading=heading, body=body, kind=kind, out_path=out_path,
            brand_color=brand_color, kicker=kicker, logo_path=logo_path,
            product_image_path=product_image_path,
        )
