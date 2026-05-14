from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import shlex
import subprocess
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont
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

    async def generate(self, product: Product, max_attempts: int = 5) -> str:
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

        image_bytes = await self._request_image_edit(headers, payload, max_attempts=max_attempts)
        output_path.write_bytes(image_bytes)
        return str(output_path)

    async def _request_image_edit(self, headers: dict[str, str], payload: dict, max_attempts: int = 5) -> bytes:
        url = f"{self.settings.freetheai_base_url.rstrip('/')}/images/edits"
        retry_statuses = {429, 500, 502, 503, 504}

        async with httpx.AsyncClient(timeout=self.settings.freetheai_timeout_seconds) as client:
            last_error = "unknown error"
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code in retry_statuses:
                        last_error = response.text[-1600:]
                        if self._is_concurrency_limit(response, last_error) and max_attempts <= 1:
                            raise ImageGenerationError(
                                "FreeTheAI сейчас занят предыдущей генерацией изображения. "
                                "Подождите 1-3 минуты и нажмите кнопку снова."
                            )
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

    def _is_concurrency_limit(self, response: httpx.Response, text: str) -> bool:
        lowered = text.lower()
        if "concurrency" in lowered or "active request" in lowered:
            return True
        try:
            error_type = ((response.json() or {}).get("error") or {}).get("type")
        except ValueError:
            return False
        return error_type == "concurrency_limit_error"

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


class PollinationsImageStyler:
    FREE_IMAGE_MODELS = {"zimage", "flux", "gptimage", "gptimage-large"}
    REFERENCE_IMAGE_MODELS = {"gptimage", "gptimage-large"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.output_dir = Path("data/styled_images")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, product: Product) -> str:
        if not self.settings.pollinations_api_key:
            raise ImageGenerationError("POLLINATIONS_API_KEY is empty. Add Pollinations key to .env or settings.")

        model = self._normalized_model()
        source_url = self._source_image_url(product)
        uses_reference = model in self.REFERENCE_IMAGE_MODELS and self.settings.image_generation_mode == "image_to_image"
        if uses_reference and not source_url:
            raise ImageGenerationError("Product has no source image URL for Pollinations image editing.")

        output_path = self.output_dir / f"product_{product.id}.png"
        payload = {
            "model": model,
            "prompt": self._build_prompt(product),
            "n": 1,
            "size": f"{self.settings.pollinations_image_width}x{self.settings.pollinations_image_height}",
            "quality": self.settings.pollinations_image_quality,
            "response_format": "b64_json",
            "safe": "true",
        }
        if source_url and uses_reference:
            payload["image"] = source_url

        headers = {
            "Authorization": f"Bearer {self.settings.pollinations_api_key}",
            "Content-Type": "application/json",
        }
        try:
            image_bytes = await self._request_image_generation(headers, payload)
        except ImageGenerationError as exc:
            if not self._is_payment_required_error(exc):
                raise
            logger.warning("Pollinations balance is empty, using branded Ozon image fallback: %s", exc)
            image_bytes = await self._build_free_source_fallback(product)
        image_bytes = self._apply_aromat_day_overlay(image_bytes, product)
        output_path.write_bytes(image_bytes)
        return str(output_path)

    def _normalized_model(self) -> str:
        model = (self.settings.pollinations_image_model or "zimage").strip()
        if model == "kontext":
            return "zimage"
        if model not in self.FREE_IMAGE_MODELS:
            logger.warning("Pollinations image model %s is not in free allowlist; using zimage", model)
            return "zimage"
        return model

    async def _request_image_generation(self, headers: dict[str, str], payload: dict) -> bytes:
        url = f"{self.settings.pollinations_base_url.rstrip('/')}/v1/images/generations"
        retry_statuses = {429, 500, 502, 503, 504}
        max_attempts = 3

        async with httpx.AsyncClient(timeout=self.settings.pollinations_image_timeout_seconds) as client:
            last_error = "unknown error"
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code == 402 and payload.get("model") != "zimage":
                        logger.warning("Pollinations model %s requires balance, retrying with zimage", payload.get("model"))
                        payload = {**payload, "model": "zimage"}
                        payload.pop("image", None)
                        response = await client.post(url, headers=headers, json=payload)
                    if response.status_code in retry_statuses:
                        last_error = response.text[-1600:]
                        if attempt < max_attempts:
                            delay = self._retry_delay(response, attempt)
                            logger.warning(
                                "Pollinations image temporary error %s on attempt %s/%s. Retrying in %.1fs: %s",
                                response.status_code,
                                attempt,
                                max_attempts,
                                delay,
                                last_error,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise ImageGenerationError(
                            f"Pollinations did not return an image after {max_attempts} attempts "
                            f"(last HTTP {response.status_code}): {last_error}"
                        )
                    response.raise_for_status()
                    return await self._extract_image_bytes(client, response.json())
                except httpx.HTTPStatusError as exc:
                    detail = exc.response.text[-1600:] if exc.response is not None else str(exc)
                    raise ImageGenerationError(f"Pollinations returned HTTP {exc.response.status_code}: {detail}") from exc
                except httpx.HTTPError as exc:
                    last_error = str(exc)
                    if attempt < max_attempts:
                        delay = min(30.0, 3.0 * attempt)
                        logger.warning(
                            "Pollinations image request failed on attempt %s/%s. Retrying in %.1fs: %s",
                            attempt,
                            max_attempts,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise ImageGenerationError(f"Pollinations image request failed after {max_attempts} attempts: {exc}") from exc

        raise ImageGenerationError(f"Pollinations did not return an image after {max_attempts} attempts: {last_error}")

    async def _extract_image_bytes(self, client: httpx.AsyncClient, result: dict) -> bytes:
        item = (result.get("data") or [{}])[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            response = await client.get(item["url"])
            response.raise_for_status()
            return response.content
        raise ImageGenerationError(f"No image found in Pollinations response: {result}")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return min(120.0, max(5.0, float(retry_after)))
            except ValueError:
                pass
        if response.status_code == 429:
            return 60.0
        if response.status_code in {500, 502, 503, 504}:
            return 30.0
        return min(30.0, 4.0 * attempt)

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

    def _is_payment_required_error(self, exc: ImageGenerationError) -> bool:
        text = str(exc)
        return "HTTP 402" in text or "PAYMENT_REQUIRED" in text or "Insufficient balance" in text

    async def _build_free_source_fallback(self, product: Product) -> bytes:
        source_url = self._source_image_url(product)
        if not source_url:
            raise ImageGenerationError("Pollinations balance is empty and product has no Ozon image for fallback.")

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; aromat-day/1.0)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers=headers) as client:
            response = await client.get(source_url)
            response.raise_for_status()

        source = Image.open(BytesIO(response.content)).convert("RGBA")
        target_w = self.settings.pollinations_image_width
        target_h = self.settings.pollinations_image_height
        canvas = Image.new("RGBA", (target_w, target_h), (15, 13, 12, 255))

        bg = source.copy()
        bg.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        bg_layer = Image.new("RGBA", (target_w, target_h), (15, 13, 12, 255))
        bg_layer.paste(bg, ((target_w - bg.width) // 2, (target_h - bg.height) // 2), bg if bg.mode == "RGBA" else None)
        bg_layer = bg_layer.filter(ImageFilter.GaussianBlur(radius=max(18, target_w // 34)))
        veil = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 118))
        canvas = Image.alpha_composite(bg_layer, veil)

        product_image = source.copy()
        product_image.thumbnail((int(target_w * 0.72), int(target_h * 0.72)), Image.Resampling.LANCZOS)
        x = (target_w - product_image.width) // 2
        y = max(24, int(target_h * 0.08))
        shadow = Image.new("RGBA", product_image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle((10, 10, product_image.width - 10, product_image.height - 10), radius=20, fill=(0, 0, 0, 95))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
        canvas.paste(shadow, (x + 8, y + 18), shadow)
        canvas.paste(product_image, (x, y), product_image if product_image.mode == "RGBA" else None)

        output = BytesIO()
        canvas.convert("RGB").save(output, format="PNG", optimize=True)
        return output.getvalue()

    def _build_prompt(self, product: Product) -> str:
        brand = product.brand or "premium fragrance"
        name = product.name or "perfume"
        if self._normalized_model() in self.REFERENCE_IMAGE_MODELS and self.settings.image_generation_mode == "image_to_image":
            return (
                "Premium edit of this real product photo for a luxury fragrance Telegram channel. "
                "Preserve the exact real bottle, packaging, label, colors and proportions. "
                "Improve only lighting, background, reflections and premium boutique look. "
                "Luxury cosmetic advertising, dark silk or glass background, warm gold accents, "
                "clean realistic product photography, absolutely no words, no typography, no watermark, no extra products. "
                f"Product context: {brand} {name}."
            )
        return (
            "Luxury premium perfume editorial image for a fragrance Telegram channel, "
            "elegant fragrance boutique mood, dark silk and glass background, warm gold light, "
            "minimal clean cosmetic advertising composition, absolutely no words, no typography, no watermark. "
            f"Product context: {brand} {name}."
        )

    def _apply_aromat_day_overlay(self, image_bytes: bytes, product: Product) -> bytes:
        image = Image.open(BytesIO(image_bytes)).convert("RGBA")
        image = self._remove_generated_corner_branding(image)
        width, height = image.size
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        gold = (224, 191, 112, 255)
        cream = (250, 244, 232, 255)
        dark = (8, 10, 16, 206)
        line = (224, 191, 112, 120)

        title_font = self._font(max(24, width // 30), bold=True)
        small_font = self._font(max(14, width // 58))
        pad = max(18, width // 34)
        bar_h = max(86, height // 11)
        y0 = height - bar_h
        draw.rectangle((0, y0, width, height), fill=dark)
        draw.line((0, y0, width, y0), fill=line, width=max(1, width // 650))

        mark_x = pad
        mark_y = y0 + max(12, bar_h // 7)
        mark_size = max(44, min(62, width // 14))
        self._draw_bottle_mark(draw, mark_x, mark_y, gold, mark_size)

        text_x = mark_x + mark_size + max(18, width // 54)
        title_y = y0 + max(20, bar_h // 4)
        subtitle_y = min(y0 + bar_h - 28, title_y + max(28, width // 30))
        draw.text((text_x, title_y), "АРОМАТ ДНЯ", fill=gold, font=title_font)
        draw.text((text_x, subtitle_y), "premium fragrance edit", fill=cream, font=small_font)

        image = Image.alpha_composite(image, overlay).convert("RGB")
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    def _remove_generated_corner_branding(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        corner_w = int(width * 0.24)
        corner_h = int(height * 0.34)
        if corner_w < 80 or corner_h < 80:
            return image

        source = image.crop((0, 0, corner_w, corner_h))
        cleaned = source.filter(ImageFilter.GaussianBlur(radius=max(18, width // 36)))
        veil = Image.new("RGBA", cleaned.size, (5, 7, 10, 92))
        cleaned = Image.alpha_composite(cleaned, veil)

        mask = Image.new("L", cleaned.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rectangle((0, 0, corner_w, corner_h), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(18, width // 42)))

        result = image.copy()
        result.paste(cleaned, (0, 0), mask)
        return result

    def _draw_bottle_mark(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        color: tuple[int, int, int, int],
        size: int,
    ) -> None:
        scale = size / 74
        cx = x + int(32 * scale)
        cy = y + int(14 * scale)
        for idx in range(21):
            angle = math.radians(205 + idx * 6.5)
            x2 = cx + int(math.cos(angle) * 42 * scale)
            y2 = cy + int(math.sin(angle) * 42 * scale)
            draw.line((cx, cy, x2, y2), fill=(color[0], color[1], color[2], 120), width=1)
        stroke = max(2, int(3 * scale))
        draw.rounded_rectangle(
            (x + int(18 * scale), y + int(34 * scale), x + int(56 * scale), y + int(72 * scale)),
            radius=max(4, int(6 * scale)),
            outline=color,
            width=stroke,
        )
        draw.rounded_rectangle(
            (x + int(24 * scale), y + int(17 * scale), x + int(50 * scale), y + int(35 * scale)),
            radius=max(4, int(5 * scale)),
            outline=color,
            width=stroke,
        )
        draw.line((x + int(24 * scale), y + int(35 * scale), x + int(24 * scale), y + int(44 * scale)), fill=color, width=stroke)
        draw.line((x + int(50 * scale), y + int(35 * scale), x + int(50 * scale), y + int(44 * scale)), fill=color, width=stroke)

    def _overlay_chips(self, product: Product) -> list[str]:
        text = " ".join(
            value.lower()
            for value in (product.name, product.brand, product.category, product.description)
            if value
        )
        chips = ["аромат", "premium"]
        if any(word in text for word in ("цвет", "rose", "floral", "жасмин", "роза", "пион")):
            chips.insert(1, "floral")
        elif any(word in text for word in ("wood", "дерев", "кожа", "amber", "амб")):
            chips.insert(1, "warm")
        elif any(word in text for word in ("fresh", "свеж", "citrus", "цитрус", "green")):
            chips.insert(1, "fresh")
        else:
            chips.insert(1, "soft")
        return chips[:3]

    def _font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
        return ImageFont.load_default()


class CloudflareWorkerImageStyler(PollinationsImageStyler):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    async def generate(self, product: Product) -> str:
        if not self.settings.cloudflare_worker_url:
            raise ImageGenerationError("CLOUDFLARE_WORKER_URL is empty. Add your Cloudflare Worker URL to .env or settings.")
        if not self.settings.cloudflare_worker_api_key:
            raise ImageGenerationError("CLOUDFLARE_WORKER_API_KEY is empty. Add your Worker API key to .env or settings.")

        output_path = self.output_dir / f"product_{product.id}.png"
        payload = {"prompt": self._build_prompt(product)}
        headers = {
            "Authorization": f"Bearer {self.settings.cloudflare_worker_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.settings.cloudflare_worker_timeout_seconds) as client:
            response = await client.post(self.settings.cloudflare_worker_url.rstrip("/"), headers=headers, json=payload)
            if response.status_code >= 400:
                detail = response.text[-1600:]
                raise ImageGenerationError(f"Cloudflare Worker returned HTTP {response.status_code}: {detail}")
            image_bytes = response.content

        image_bytes = self._apply_aromat_day_overlay(image_bytes, product)
        output_path.write_bytes(image_bytes)
        return str(output_path)
