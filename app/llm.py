from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

import httpx

from app.schemas import ProductData

logger = logging.getLogger(__name__)

StyleName = Literal["info", "selling", "premium", "short", "long"]

STYLE_HINTS: dict[str, str] = {
    "info": "информационный, спокойный, полезный, без лишней рекламности",
    "selling": "мягко продающий, убедительный, но без агрессивного давления",
    "premium": "премиальный, эстетичный, женственный, аккуратный, с ощущением дорогого Telegram-бутика",
    "short": "короткий Telegram-пост до 700 символов, выразительный и чистый",
    "long": "подробный Telegram-пост с хорошей структурой, атмосферой и удобной читаемостью",
}

PREMIUM_EMOJI_RULES = """
Эмодзи:
- используй 3-7 premium-эмодзи на весь пост, не в каждой строке;
- подходят: ✨, 🤍, 🕊️, 🪞, 🌙, 💫, 🥂, 🖤, 🪷, 🧴;
- не используй дешёвые/кричащие эмодзи и слишком много огня, сирен, денег, капса;
- эмодзи должны подчёркивать эстетику, а не заменять смысл.
""".strip()


class TextGenerationError(RuntimeError):
    pass


class ProductPromptBuilder:
    def _build_prompt(self, product: ProductData, style: StyleName) -> str:
        data = self._compact_product_data(product)
        return f"""
Ты — редактор красивого Telegram-канала "Аромат дня" о парфюмерии, уходе и эстетике.
На основе данных о товаре создай готовый пост на русском языке: лёгкий, премиальный, живой и аккуратно продающий.

Стиль: {STYLE_HINTS[style]}.

Тональность:
- ощущение дорогого бутика, личной рекомендации и спокойной эстетики;
- больше воздуха, короткие абзацы, мягкий ритм, без тяжёлых канцелярских формулировок;
- без базарной рекламы, давления, капса и фраз вроде "успей купить";
- не делай текст похожим на техническую карточку товара.

{PREMIUM_EMOJI_RULES}

Жёсткие требования:
- не выдумывай характеристики, ноты, бренд, объём, страну или эффекты, которых нет в данных;
- если данных о нотах нет, не перечисляй ноты;
- не обещай лечебных, стойких или оригинальных свойств, если это не указано в данных;
- не искажай цену, объём, название и бренд;
- если данных мало, пиши аккуратно и обобщённо, без фантазий;
- текст должен быть живым, эстетичным и удобным для Telegram;
- характеристики не перечисляй длинной простынёй: выбери только 3-5 самых важных и оформи красиво;
- цену можно указать, если она есть, но без ощущения жёсткой продажи;
- не вставляй сырой URL в текст поста;
- если в данных есть поле url, напиши ближе к концу: "Заказать можно по кнопке ниже";
- добавь мягкий короткий призыв к действию без давления;
- в конце добавь 3-6 релевантных хэштегов.

Структура:
1. Эстетичный заголовок с 1 premium-эмодзи.
2. 2-3 коротких абзаца: ощущение, настроение, кому подойдёт.
3. Небольшой блок "Детали" с 3-5 пунктами только из исходных данных.
4. Мягкая фраза "Заказать можно по кнопке ниже", если есть url.
5. Хэштеги.

Запрещено:
- длинные сухие списки характеристик;
- фразы "главные характеристики:" если дальше идёт много строк;
- сырой URL;
- медицинские обещания;
- выдуманные ноты и эффекты.

Исходные данные о товаре в JSON:
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()

    def _clean(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
        return text

    def _compact_product_data(self, product: ProductData) -> dict:
        data = product.model_dump(mode="json")
        if data.get("description"):
            data["description"] = str(data["description"])[:1800]
        data["attributes"] = data.get("attributes", [])[:30]
        data["images"] = data.get("images", [])[:3]
        return data


class OllamaGenerator(ProductPromptBuilder):
    def __init__(self, base_url: str, model: str, timeout_seconds: int = 300, num_predict: int = 650) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.num_predict = num_predict

    async def generate_post(self, product: ProductData, style: StyleName = "premium") -> str:
        prompt = self._build_prompt(product, style)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": self.num_predict,
                "num_ctx": 4096,
            },
        }
        timeout = httpx.Timeout(self.timeout_seconds, connect=15)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        return self._clean(data.get("response", ""))


class FreeTheAITextGenerator(ProductPromptBuilder):
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout_seconds: int = 180,
        max_tokens: int = 900,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens

    async def generate_post(self, product: ProductData, style: StyleName = "premium") -> str:
        if not self.api_key:
            raise TextGenerationError("FREETHEAI_API_KEY is empty. Add FreeTheAI key to .env or settings.")

        prompt = self._build_prompt(product, style)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты пишешь премиальные Telegram-посты о парфюмерии на русском языке. "
                        "Нельзя выдумывать факты о товаре. Ответ возвращай только готовым текстом поста."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.72,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        result = await self._request_chat_completion(headers, payload)
        choices = result.get("choices") or []
        if not choices:
            raise TextGenerationError(f"FreeTheAI response has no choices: {result}")
        content = (choices[0].get("message") or {}).get("content") or choices[0].get("text") or ""
        if not content:
            raise TextGenerationError(f"FreeTheAI response has no text content: {result}")
        return self._clean(content)

    async def _request_chat_completion(self, headers: dict[str, str], payload: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        retry_statuses = {429, 500, 502, 503, 504}
        max_attempts = 5

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            last_error = "unknown error"
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code in retry_statuses:
                        last_error = response.text[-1600:]
                        if attempt < max_attempts:
                            delay = self._retry_delay(response, attempt)
                            logger.warning(
                                "FreeTheAI text temporary error %s on attempt %s/%s. Retrying in %.1fs: %s",
                                response.status_code,
                                attempt,
                                max_attempts,
                                delay,
                                last_error,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise TextGenerationError(
                            f"FreeTheAI text did not return an answer after {max_attempts} attempts "
                            f"(last HTTP {response.status_code}): {last_error}"
                        )
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    detail = exc.response.text[-1600:] if exc.response is not None else str(exc)
                    raise TextGenerationError(f"FreeTheAI text returned HTTP {exc.response.status_code}: {detail}") from exc
                except httpx.HTTPError as exc:
                    last_error = str(exc)
                    if attempt < max_attempts:
                        delay = min(30.0, 3.0 * attempt)
                        logger.warning(
                            "FreeTheAI text request failed on attempt %s/%s. Retrying in %.1fs: %s",
                            attempt,
                            max_attempts,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise TextGenerationError(f"FreeTheAI text request failed after {max_attempts} attempts: {exc}") from exc

        raise TextGenerationError(f"FreeTheAI text did not return an answer after {max_attempts} attempts: {last_error}")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return min(60.0, max(1.0, float(retry_after)))
            except ValueError:
                pass
        if response.status_code in {429, 500, 502, 503, 504}:
            return 180.0
        return min(30.0, 4.0 * attempt)
