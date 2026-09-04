"""
Script / storyboard generation.

Turns a ProductInput into a list of Scene objects. The number of scenes is
derived from the data (1 intro + 1 per feature + 1 audience beat + 1 CTA),
so a product with 3 features gets a short video and a product with 40
features gets a long one -- nothing here clamps the list length or scene
duration. Long feature lists are automatically grouped into "chapters" by
the assembler (see assembler.py) rather than truncated.

This module is intentionally template-based (no external LLM call, so it
works fully offline in this environment) but exposes a `ScriptGenerator`
interface so a real LLM (Claude via the Anthropic API, GPT, etc.) can be
swapped in for punchier copywriting without touching the rest of the
pipeline -- see LLMScriptGenerator stub at the bottom.
"""
from __future__ import annotations

import textwrap
from typing import List

from core.models import ProductInput, Scene

TONE_OPENERS = {
    "energetic": "Introducing",
    "professional": "Presenting",
    "calm": "Meet",
}

TONE_FEATURE_LEADIN = {
    "energetic": "Check this out:",
    "professional": "Key capability:",
    "calm": "You'll also love:",
}


class ScriptGenerator:
    """Base interface. Swap in a subclass to change how copy is written."""

    def generate(self, product: ProductInput) -> List[Scene]:
        raise NotImplementedError


class TemplateScriptGenerator(ScriptGenerator):
    """Deterministic, offline, no external API required."""

    def generate(self, product: ProductInput) -> List[Scene]:
        scenes: List[Scene] = []
        opener = TONE_OPENERS.get(product.tone, "Introducing")

        # --- Intro ---------------------------------------------------
        scenes.append(
            Scene(
                index=0,
                kind="intro",
                heading=product.name,
                body=self._wrap(product.description, 70),
                voiceover=f"{opener} {product.name}. {product.description}",
            )
        )

        # --- One scene per feature (unbounded) ------------------------
        leadin = TONE_FEATURE_LEADIN.get(product.tone, "Key capability:")
        for i, feature in enumerate(product.features, start=1):
            words = feature.split(":")[0].split()
            short_heading = " ".join(words[:4]) + ("…" if len(words) > 4 else "")
            scenes.append(
                Scene(
                    index=len(scenes),
                    kind="feature",
                    heading=short_heading,
                    body=self._wrap(feature.rstrip("."), 70),
                    voiceover=f"{leadin} {feature}.",
                )
            )

        # --- Audience beat --------------------------------------------
        if product.target_audience:
            scenes.append(
                Scene(
                    index=len(scenes),
                    kind="audience",
                    heading="Built for you",
                    body=self._wrap(f"Perfect for {product.target_audience}.", 70),
                    voiceover=f"{product.name} is built for {product.target_audience}.",
                )
            )

        # --- Call to action ---------------------------------------------
        scenes.append(
            Scene(
                index=len(scenes),
                kind="cta",
                heading=product.name,
                body=self._wrap(product.call_to_action, 70),
                voiceover=f"{product.call_to_action}",
            )
        )
        return scenes

    @staticmethod
    def _wrap(text: str, width: int) -> str:
        return "\n".join(textwrap.wrap(text, width=width)) or text


class LLMScriptGenerator(ScriptGenerator):
    """
    Stub showing where a real LLM call would plug in (e.g. the Anthropic
    Messages API) to generate sharper marketing copy per scene while
    reusing the exact same Scene structure and downstream rendering code.
    Not wired up by default because this environment has no outbound
    network access; kept here so the swap is a one-line change in
    pipeline.py (`generator = LLMScriptGenerator(api_key=...)`).
    """

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model

    def generate(self, product: ProductInput) -> List[Scene]:
        # Fall back to the template generator if no key/network is available.
        return TemplateScriptGenerator().generate(product)
