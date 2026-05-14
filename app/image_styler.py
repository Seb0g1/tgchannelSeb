from __future__ import annotations

import asyncio
import json
import logging
from io import BytesIO
from pathlib import Path

import httpx
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

        mode = "cover" if self.settings.image_generation_mode == "cover" else "image_to_image"
        prompt = self._build_prompt(product, mode)
        output_path = self.output_dir / f"product_{product.id}.png"
        source_image = await self._download_source_image(product) if mode == "image_to_image" else None

        if mode == "image_to_image" and source_image is None:
            raise ImageGenerationError("Product has no downloadable source image for premium processing.")

        def run_generation() -> None:
            provider = None if self.settings.hf_image_provider == "auto" else self.settings.hf_image_provider
            client = InferenceClient(provider=provider, token=self.settings.hf_token, timeout=180)
            if mode == "image_to_image" and source_image is not None:
                image = client.image_to_image(
                    image=source_image,
                    prompt=prompt,
                    model=self.settings.hf_image_model,
                    negative_prompt=self._negative_prompt(),
                    guidance_scale=6.5,
                    num_inference_steps=30,
                    target_size={"width": self.settings.hf_image_width, "height": self.settings.hf_image_height},
                )
            else:
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

    async def _download_source_image(self, product: Product) -> BytesIO | None:
        source_url = self._source_image_url(product)
        if source_url is None:
            return None

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; aromat-day/1.0)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=True, headers=headers) as client:
                response = await client.get(source_url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "image" not in content_type:
                    logger.warning("Source URL did not return an image: %s (%s)", source_url, content_type)
                    return None
        except httpx.HTTPError as exc:
            logger.warning("Could not download source product image %s: %s", source_url, exc)
            return None

        image = BytesIO(response.content)
        image.name = "source_product.jpg"
        image.seek(0)
        return image

    def _source_image_url(self, product: Product) -> str | None:
        try:
            images = json.loads(product.images_json or "[]")
        except json.JSONDecodeError:
            images = []
        if not isinstance(images, list):
            return None
        for image in images:
            if isinstance(image, str) and image.startswith("http"):
                return image
        return None

    def _build_prompt(self, product: Product, mode: str) -> str:
        brand = product.brand or "premium fragrance"
        name = product.name or "perfume"
        if mode == "image_to_image":
            return (
                'Premium edit of this real perfume product photo for Telegram channel "Аромат дня". '
                "Keep the exact product identity unchanged: same bottle shape, same packaging, same label, "
                "same colors, same cap, same proportions. Improve only presentation, lighting, background, "
                "contrast and reflections. Elegant luxury perfume editorial scene, soft studio light, "
                "dark silk or glass background, subtle warm gold accents, clean premium cosmetic advertising style, "
                "vertical 4:5 composition, realistic product photography, no text, no new logo, no watermark. "
                f"Product context: {brand} {name}."
            )
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
            "changed product, different bottle, different packaging, fake label, fake logo, text, watermark, "
            "cheap design, low quality, blurry, distorted bottle, extra bottles, clutter, cartoon, "
            "oversaturated, bad reflections, people, hands"
        )
