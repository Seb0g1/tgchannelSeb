from __future__ import annotations

import asyncio
import base64
import json
import logging
import shlex
import subprocess
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image
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


class LocalSdcppImageStyler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.output_dir = Path("data/styled_images")
        self.source_dir = Path("data/source_images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.source_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, product: Product) -> str:
        binary_path = Path(self.settings.local_sdcpp_bin)
        model_path = Path(self.settings.local_image_model)
        if not binary_path.exists():
            raise ImageGenerationError(f"stable-diffusion.cpp binary not found: {binary_path}")
        if not model_path.exists():
            raise ImageGenerationError(f"Local image model not found: {model_path}")

        source_image = await self._download_source_image(product)
        if source_image is None:
            raise ImageGenerationError("Product has no downloadable source image for local premium processing.")

        source_path = self.source_dir / f"product_{product.id}_source.png"
        output_path = self.output_dir / f"product_{product.id}.png"
        self._save_source_png(source_image, source_path)

        command = [
            str(binary_path),
            "-m",
            str(model_path),
            "-p",
            self._build_prompt(product),
            "-n",
            self._negative_prompt(),
            "-i",
            str(source_path),
            "-o",
            str(output_path),
            "-W",
            str(self.settings.local_image_width),
            "-H",
            str(self.settings.local_image_height),
            "--steps",
            str(self.settings.local_image_steps),
            "--strength",
            str(self.settings.local_image_strength),
            "--cfg-scale",
            str(self.settings.local_image_cfg_scale),
            "-s",
            str(self.settings.local_image_seed),
            "-t",
            str(self.settings.local_image_threads),
            "--rng",
            "cpu",
            "--vae-tiling",
        ]

        def run_generation() -> None:
            logger.info("Running local image generation: %s", " ".join(shlex.quote(part) for part in command))
            completed = subprocess.run(
                command,
                cwd=str(Path.cwd()),
                capture_output=True,
                text=True,
                timeout=self.settings.local_image_timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "local generation failed").strip()
                raise ImageGenerationError(message[-1600:])
            if not output_path.exists():
                raise ImageGenerationError("stable-diffusion.cpp finished without creating output image.")

        try:
            await asyncio.to_thread(run_generation)
        except subprocess.TimeoutExpired as exc:
            raise ImageGenerationError(f"Local image generation timed out after {exc.timeout} seconds.") from exc
        except ImageGenerationError:
            raise
        except Exception as exc:
            logger.exception("Local image generation failed")
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
        image.seek(0)
        return image

    def _save_source_png(self, source_image: BytesIO, source_path: Path) -> None:
        with Image.open(source_image) as image:
            image.convert("RGB").save(source_path, format="PNG")

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

    def _build_prompt(self, product: Product) -> str:
        brand = product.brand or "premium fragrance"
        name = product.name or "perfume"
        return (
            "premium perfume product photo, preserve the exact real bottle and packaging, "
            "same label, same colors, elegant luxury studio lighting, dark silk background, "
            "glass reflections, subtle gold accents, clean expensive cosmetic advertising, "
            "realistic product photography, high detail, no text, no watermark, "
            f"{brand} {name}"
        )

    def _negative_prompt(self) -> str:
        return (
            "different bottle, changed label, fake logo, changed packaging, text, watermark, "
            "blurry, low quality, distorted product, extra bottle, hands, people, cartoon"
        )


class FreeTheAIImageStyler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.output_dir = Path("data/styled_images")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, product: Product) -> str:
        if not self.settings.freetheai_api_key:
            raise ImageGenerationError("FREETHEAI_API_KEY is empty. Add FreeTheAI key to .env or settings.")

        source_image = await self._download_source_image(product)
        if source_image is None:
            raise ImageGenerationError("Product has no downloadable source image for FreeTheAI edit.")

        output_path = self.output_dir / f"product_{product.id}.png"
        data_url = self._image_data_url(source_image)
        payload = {
            "model": self.settings.freetheai_image_model,
            "prompt": self._build_prompt(product),
            "image": data_url,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.freetheai_api_key}",
            "Content-Type": "application/json",
        }

        image_bytes = await self._request_image_edit(headers, payload)
        output_path.write_bytes(image_bytes)
        return str(output_path)

    async def _request_image_edit(self, headers: dict[str, str], payload: dict) -> bytes:
        url = f"{self.settings.freetheai_base_url.rstrip('/')}/images/edits"
        retry_statuses = {429, 500, 502, 503, 504}
        max_attempts = 5

        async with httpx.AsyncClient(timeout=self.settings.freetheai_timeout_seconds) as client:
            last_error = "unknown error"
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code in retry_statuses:
                        last_error = response.text[-1600:]
                        if attempt < max_attempts:
                            delay = self._retry_delay(response, attempt)
                            logger.warning(
                                "FreeTheAI temporary error %s on attempt %s/%s. Retrying in %.1fs: %s",
                                response.status_code,
                                attempt,
                                max_attempts,
                                delay,
                                last_error,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise ImageGenerationError(
                            f"FreeTheAI did not return an image after {max_attempts} attempts "
                            f"(last HTTP {response.status_code}): {last_error}"
                        )
                    response.raise_for_status()
                    return await self._extract_image_bytes(client, response.json())
                except httpx.HTTPStatusError as exc:
                    detail = exc.response.text[-1600:] if exc.response is not None else str(exc)
                    raise ImageGenerationError(f"FreeTheAI returned HTTP {exc.response.status_code}: {detail}") from exc
                except httpx.HTTPError as exc:
                    last_error = str(exc)
                    if attempt < max_attempts:
                        delay = min(30.0, 3.0 * attempt)
                        logger.warning(
                            "FreeTheAI request failed on attempt %s/%s. Retrying in %.1fs: %s",
                            attempt,
                            max_attempts,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise ImageGenerationError(f"FreeTheAI request failed after {max_attempts} attempts: {exc}") from exc
                except ImageGenerationError:
                    raise
                except Exception as exc:
                    logger.exception("FreeTheAI image edit failed")
                    raise ImageGenerationError(str(exc)) from exc

        raise ImageGenerationError(f"FreeTheAI did not return an image after {max_attempts} attempts: {last_error}")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                delay = max(1.0, float(retry_after))
                if response.status_code in {429, 500, 502, 503, 504}:
                    return max(60.0, delay)
                return min(60.0, delay)
            except ValueError:
                pass
        if response.status_code in {429, 500, 502, 503, 504}:
            return 60.0
        return min(30.0, 4.0 * attempt)

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
        image.seek(0)
        return image

    def _image_data_url(self, source_image: BytesIO) -> str:
        output = BytesIO()
        with Image.open(source_image) as image:
            image.convert("RGB").save(output, format="PNG")
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    async def _extract_image_bytes(self, client: httpx.AsyncClient, result: dict) -> bytes:
        item = (result.get("data") or [{}])[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            response = await client.get(item["url"])
            response.raise_for_status()
            return response.content
        raise ImageGenerationError(f"No image found in FreeTheAI response: {result}")

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

    def _build_prompt(self, product: Product) -> str:
        brand = product.brand or "premium fragrance"
        name = product.name or "perfume"
        return (
            "Improve this real perfume product photo for a premium Telegram fragrance channel. "
            "Keep the exact product identity unchanged: same bottle shape, same packaging, same label, "
            "same colors, same cap and same proportions. Do not invent another perfume. "
            "Only improve the background, lighting, contrast, reflections and overall premium look. "
            "Elegant luxury perfume editorial scene, soft studio lighting, dark silk or glass background, "
            "subtle warm gold accents, clean expensive cosmetic advertising style, realistic product photography. "
            "No text, no watermark, no fake logo, no extra products. "
            f"Product context: {brand} {name}."
        )
