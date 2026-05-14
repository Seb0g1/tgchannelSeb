from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from huggingface_hub import InferenceClient

from app.config import Settings
from app.models import Product

logger = logging.getLogger(__name__)


class ImageGenerationError(RuntimeError):
    pass


class HuggingFaceImageStyler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.output_dir = Path("data/styled_images")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, product: Product) -> str:
        if not self.settings.hf_token:
            raise ImageGenerationError("HF_TOKEN is empty. Add Hugging Face token to .env.")

        prompt = self._build_prompt(product)
        output_path = self.output_dir / f"product_{product.id}.png"

        def run_generation() -> None:
            provider = None if self.settings.hf_image_provider == "auto" else self.settings.hf_image_provider
            client = InferenceClient(
                provider=provider,
                token=self.settings.hf_token,
                timeout=180,
            )
            image = client.text_to_image(
                prompt,
                model=self.settings.hf_image_model,
                width=self.settings.hf_image_width,
                height=self.settings.hf_image_height,
                negative_prompt=self._negative_prompt(),
            )
            image.save(output_path)

        try:
            await asyncio.to_thread(run_generation)
        except Exception as exc:
            logger.exception("Hugging Face image generation failed")
            raise ImageGenerationError(str(exc)) from exc

        return str(output_path)

    def _build_prompt(self, product: Product) -> str:
        brand = product.brand or "premium fragrance"
        name = product.name or "perfume"
        return (
            'Luxury perfume editorial cover for Telegram channel "Аромат дня". '
            "High-end fragrance boutique aesthetic, elegant perfume bottle silhouette, "
            "dark silk and glass background, soft golden studio lighting, subtle reflections, "
            "minimal premium composition, feminine luxury mood, expensive cosmetic advertising style, "
            "vertical 4:5 cover, no text, no logo, no watermark. "
            f"Product context: {brand} {name}."
        )

    def _negative_prompt(self) -> str:
        return (
            "cheap design, low quality, blurry, distorted bottle, unreadable text, fake logo, "
            "watermark, extra bottles, clutter, cartoon, oversaturated, bad anatomy, people, hands"
        )
