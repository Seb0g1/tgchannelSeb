from __future__ import annotations

import json
from typing import Literal

import httpx

from app.schemas import ProductData

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
- не используй дешевые/кричащие эмодзи и слишком много огня, сирен, денег, капсов;
- эмодзи должны подчеркивать эстетику, а не заменять смысл.
""".strip()


class OllamaGenerator:
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

    def _build_prompt(self, product: ProductData, style: StyleName) -> str:
        data = self._compact_product_data(product)
        return f"""
Ты — контент-редактор премиального Telegram-канала о парфюмерии.
На основе данных о товаре создай красивый пост для Telegram на русском языке.

Стиль: {STYLE_HINTS[style]}.

Тональность:
- дорого, чисто, эстетично;
- женственно или универсально, если пол не указан;
- без базарной рекламы, давления и фраз вроде "успей купить";
- текст должен звучать как рекомендация в красивом парфюмерном бутике.

{PREMIUM_EMOJI_RULES}

Жесткие требования:
- не выдумывай характеристики, ноты, бренд, объем, страну или эффекты, которых нет в данных;
- если данных о нотах нет, не перечисляй ноты;
- не обещай лечебных, стойких или оригинальных свойств, если это не указано в данных;
- не искажай цену, объем, название и бренд;
- если данных мало, пиши аккуратно и обобщенно, без фантазий;
- текст должен быть живым, эстетичным и удобным для Telegram;
- добавь мягкий короткий призыв к действию;
- если в данных есть поле url, обязательно добавь ссылку для заказа отдельной строкой ближе к концу;
- в конце добавь 3-6 релевантных хэштегов.

Структура:
1. Цепляющий заголовок с 1 эмодзи.
2. Короткое атмосферное описание аромата.
3. Кому подойдет / настроение аромата.
4. Основные характеристики только из исходных данных.
5. Мягкий призыв к действию и ссылка для заказа, если она есть.
6. Хэштеги.

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
