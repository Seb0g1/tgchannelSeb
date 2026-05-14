from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.schemas import ProductData

logger = logging.getLogger(__name__)


class OzonClient:
    def __init__(self, client_id: str, api_key: str, base_url: str, visibility: str = "VISIBLE") -> None:
        self.base_url = base_url.rstrip("/")
        self.visibility = visibility
        self.headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json",
        }
        self._browser_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Referer": "https://www.ozon.ru/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def fetch_products(self, limit: int = 20) -> list[ProductData]:
        product_ids = await self._fetch_product_ids(limit)
        if not product_ids:
            return []

        details = await self._fetch_details(product_ids)
        attributes = await self._fetch_attributes(product_ids)
        descriptions = await self._fetch_descriptions(product_ids)
        prices = await self._fetch_prices(product_ids)
        stocks = await self._fetch_stocks(product_ids)

        by_id_attrs = {str(item.get("id") or item.get("product_id")): item for item in attributes}
        by_id_description = descriptions
        by_id_price = {str(item.get("product_id") or item.get("id")): item for item in prices}
        by_id_stock = {str(item.get("product_id") or item.get("id")): item for item in stocks}

        products: list[ProductData] = []
        for item in details:
            product_id = str(item.get("id") or item.get("product_id") or "")
            offer_id = str(item.get("offer_id") or product_id)
            attr_item = by_id_attrs.get(product_id, {})
            price_item = by_id_price.get(product_id, {})
            stock_item = by_id_stock.get(product_id, {})
            attrs = self._normalize_attributes(attr_item or item)
            images = self._extract_images(item, attr_item)
            description = by_id_description.get(product_id) or item.get("description") or attr_item.get("description")
            products.append(
                ProductData(
                    offer_id=offer_id,
                    product_id=product_id or None,
                    sku=str(item.get("sku")) if item.get("sku") else None,
                    name=str(item.get("name") or attr_item.get("name") or offer_id),
                    brand=self._find_attribute(attrs, ("Бренд", "Brand", "brand")),
                    category=item.get("category_name") or attr_item.get("category_name"),
                    description=description,
                    attributes=attrs,
                    images=images,
                    price=self._extract_price(price_item, item),
                    stock=self._extract_stock(stock_item, item),
                    url=self._extract_url(item),
                    visibility=str(item.get("visibility") or self.visibility),
                    is_active=self._is_active(item, stock_item),
                )
            )
        return products

    async def fetch_public_price(self, product_url: str | None) -> str | None:
        if not product_url:
            return None
        normalized = str(product_url).strip()
        if not normalized.startswith(("http://", "https://")):
            return None

        html = await self._fetch_public_page_html(normalized)
        if html:
            price = self._extract_public_price_from_html(html)
            if price:
                return price

        html = await self._fetch_public_page_html_with_playwright(normalized)
        if html:
            return self._extract_public_price_from_html(html)
        return None

    async def _fetch_product_ids(self, limit: int) -> list[str]:
        items: list[dict[str, Any]] = []
        last_id = ""
        while len(items) < limit:
            payload = {
                "filter": {"visibility": self.visibility},
                "last_id": last_id,
                "limit": min(100, limit - len(items)),
            }
            data = await self._post("/v3/product/list", payload)
            result = data.get("result", {})
            batch = result.get("items", [])
            if not batch:
                break
            items.extend(batch)
            last_id = result.get("last_id") or ""
            if not last_id:
                break
        ids = [str(item.get("product_id")) for item in items if item.get("product_id")]
        logger.info("Fetched %s Ozon product ids", len(ids))
        return ids[:limit]

    async def fetch_all_product_ids(self, limit: int = 30000) -> list[str]:
        return await self._fetch_product_ids(limit)

    async def _fetch_details(self, product_ids: list[str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for chunk in self._chunks(product_ids, 1000):
            data = await self._post("/v3/product/info/list", {"product_id": chunk})
            items.extend(data.get("items") or data.get("result", {}).get("items", []))
        return items

    async def _fetch_attributes(self, product_ids: list[str]) -> list[dict[str, Any]]:
        try:
            items: list[dict[str, Any]] = []
            for chunk in self._chunks(product_ids, 1000):
                data = await self._post(
                    "/v4/product/info/attributes",
                    {"filter": {"product_id": chunk, "visibility": "ALL"}, "limit": len(chunk)},
                )
                result = data.get("result", {})
                if isinstance(result, dict):
                    items.extend(result.get("items") or [])
                elif isinstance(result, list):
                    items.extend(result)
            return items
        except httpx.HTTPError as exc:
            logger.warning("Ozon attributes endpoint failed: %s", exc)
            return []

    async def _fetch_descriptions(self, product_ids: list[str]) -> dict[str, str]:
        descriptions: dict[str, str] = {}
        for product_id in product_ids:
            try:
                data = await self._post("/v1/product/info/description", {"product_id": int(product_id)})
                result = data.get("result", {})
                value = result.get("description") or result.get("content")
                if value:
                    descriptions[product_id] = value
            except httpx.HTTPError as exc:
                logger.info("No separate Ozon description for product %s: %s", product_id, exc)
        return descriptions

    async def _fetch_prices(self, product_ids: list[str]) -> list[dict[str, Any]]:
        for path in ("/v5/product/info/prices", "/v4/product/info/prices"):
            items: list[dict[str, Any]] = []
            failed = False
            for chunk in self._chunks(product_ids, 1000):
                try:
                    data = await self._post(path, {"filter": {"product_id": chunk}, "limit": len(chunk)})
                    result = data.get("result", {})
                    items.extend(result.get("items") or data.get("items") or [])
                except httpx.HTTPError as exc:
                    logger.warning("Ozon prices endpoint %s failed: %s", path, exc)
                    failed = True
                    break
            if not failed:
                return items
        return []

    async def _fetch_stocks(self, product_ids: list[str]) -> list[dict[str, Any]]:
        try:
            items: list[dict[str, Any]] = []
            for chunk in self._chunks(product_ids, 1000):
                data = await self._post(
                    "/v4/product/info/stocks",
                    {"filter": {"product_id": chunk}, "limit": len(chunk)},
                )
                result = data.get("result", {})
                items.extend(result.get("items") or data.get("items") or [])
            return items
        except httpx.HTTPError as exc:
            logger.warning("Ozon stocks endpoint failed: %s", exc)
            return []

    async def _fetch_public_page_html(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(
                headers=self._browser_headers,
                follow_redirects=True,
                timeout=httpx.Timeout(30, connect=10),
            ) as client:
                response = await client.get(url)
            if response.status_code in {403, 429}:
                logger.info("Ozon public page blocked with HTTP %s for %s", response.status_code, url)
                return None
            response.raise_for_status()
            text = response.text
            if "Antibot Challenge Page" in text:
                return None
            return text
        except httpx.HTTPError as exc:
            logger.info("Ozon public page fetch failed for %s: %s", url, exc)
            return None

    async def _fetch_public_page_html_with_playwright(self, url: str) -> str | None:
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception:
            return None

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = await browser.new_context(
                    user_agent=self._browser_headers["User-Agent"],
                    locale="ru-RU",
                    viewport={"width": 1440, "height": 1600},
                )
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=45000)
                html = await page.content()
                await context.close()
                await browser.close()
                if "Antibot Challenge Page" in html:
                    return None
                return html
        except Exception as exc:
            logger.info("Ozon public page playwright failed for %s: %s", url, exc)
            return None

    def _extract_public_price_from_html(self, html: str) -> str | None:
        for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
            try:
                data = json.loads(block.strip())
            except Exception:
                continue
            price = self._find_price_in_json(data)
            if price:
                return price

        patterns = [
            r'"currentPrice"\s*:\s*\{[^{}]{0,200}?"value"\s*:\s*"?(?P<price>\d[\d\s.,]*)',
            r'"salePrice"\s*:\s*\{[^{}]{0,200}?"value"\s*:\s*"?(?P<price>\d[\d\s.,]*)',
            r'"price"\s*:\s*\{[^{}]{0,200}?"value"\s*:\s*"?(?P<price>\d[\d\s.,]*)',
            r'"currentPrice"\s*:\s*"?(?P<price>\d[\d\s.,]*)',
            r'"salePrice"\s*:\s*"?(?P<price>\d[\d\s.,]*)',
            r'"price"\s*:\s*"?(?P<price>\d[\d\s.,]*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.I | re.S)
            if not match:
                continue
            price = self._format_price(match.group("price"), "RUB")
            if price:
                return price
        return None

    def _find_price_in_json(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("price", "lowPrice", "highPrice", "currentPrice", "salePrice", "discountPrice"):
                if key not in value:
                    continue
                price = self._format_price(value.get(key), value.get("priceCurrency") or value.get("currency"))
                if price:
                    return price
            for nested in value.values():
                price = self._find_price_in_json(nested)
                if price:
                    return price
        elif isinstance(value, list):
            for nested in value:
                price = self._find_price_in_json(nested)
                if price:
                    return price
        return None

    def _normalize_attributes(self, item: dict[str, Any]) -> list[dict[str, str]]:
        attrs = item.get("attributes") or []
        normalized: list[dict[str, str]] = []
        for attr in attrs:
            name = str(attr.get("attribute_name") or attr.get("name") or attr.get("id") or "").strip()
            values = attr.get("values") or []
            if isinstance(values, list):
                value = ", ".join(str(v.get("value") if isinstance(v, dict) else v) for v in values if v)
            else:
                value = str(values)
            if name and value:
                normalized.append({"name": name, "value": value})
        return normalized

    def _find_attribute(self, attrs: list[dict[str, str]], names: tuple[str, ...]) -> str | None:
        lowered = {name.lower() for name in names}
        for attr in attrs:
            if attr["name"].lower() in lowered:
                return attr["value"]
        return None

    def _extract_images(self, *items: dict[str, Any]) -> list[str]:
        images: list[str] = []
        for item in items:
            for key in ("primary_image", "images", "images360"):
                raw = item.get(key)
                if isinstance(raw, str):
                    images.append(raw)
                elif isinstance(raw, list):
                    images.extend(str(value) for value in raw if value)
        return list(dict.fromkeys(images))

    def _extract_price(self, *items: dict[str, Any]) -> str | None:
        discount_candidates: list[tuple[float, str | None]] = []
        fallback_candidates: list[tuple[float, str | None]] = []
        for item in items:
            if not item:
                continue
            price_block = item.get("price") if isinstance(item.get("price"), dict) else item
            currency = price_block.get("currency_code") or item.get("currency_code")
            for key in (
                "marketing_seller_price",
                "marketing_price",
                "auto_action_price",
                "min_price",
                "discount_price",
                "client_price",
                "seller_price",
                "ozon_price",
                "price",
            ):
                self._append_price_candidate(discount_candidates, price_block.get(key), currency)
                self._append_price_candidate(discount_candidates, item.get(key), currency)
            self._append_price_candidate(fallback_candidates, price_block.get("old_price"), currency)
            self._append_price_candidate(fallback_candidates, item.get("old_price"), currency)

            actions = item.get("actions") or price_block.get("actions") or []
            if isinstance(actions, list):
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    action_currency = action.get("currency_code") or currency
                    for key in ("price", "action_price", "discount_price", "marketing_price"):
                        self._append_price_candidate(discount_candidates, action.get(key), action_currency)

        candidates = discount_candidates or fallback_candidates
        if not candidates:
            return None
        value, currency = min(candidates, key=lambda candidate: candidate[0])
        return self._format_price(value, currency)

    def _append_price_candidate(
        self,
        candidates: list[tuple[float, str | None]],
        raw_price: Any,
        currency: str | None,
    ) -> None:
        value = self._parse_price(raw_price)
        if value is None:
            return
        if 100 <= value <= 500_000:
            candidates.append((value, currency))

    def _parse_price(self, raw_price: Any) -> float | None:
        if raw_price in (None, "", "0", 0):
            return None
        if isinstance(raw_price, (int, float)):
            return float(raw_price)
        text = str(raw_price).strip().replace(" ", "").replace("\u00a0", "")
        text = text.replace("\u20bd", "").replace("руб.", "").replace("руб", "")
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None

    def _format_price(self, price: Any, currency: str | None) -> str:
        try:
            value = float(price)
            rendered = f"{value:,.0f}".replace(",", " ") if value.is_integer() else f"{value:,.2f}".replace(",", " ")
        except (TypeError, ValueError):
            rendered = str(price)
        if currency == "RUB" or currency is None:
            return f"{rendered} \u20bd"
        return f"{rendered} {currency}"

    def _extract_url(self, item: dict[str, Any]) -> str | None:
        sku = item.get("sku")
        if sku:
            return f"https://www.ozon.ru/product/{sku}/"
        return None

    def _is_active(self, item: dict[str, Any], stock_item: dict[str, Any]) -> bool:
        visibility = str(item.get("visibility") or self.visibility).upper()
        if visibility in {"ARCHIVED", "DISABLED", "INVISIBLE", "DELETED"}:
            return False
        stock = self._extract_stock(stock_item, item)
        if stock is not None:
            return stock > 0
        return visibility in {"VISIBLE", "ALL", "IN_SALE", "ACTIVE"}

    def _chunks(self, values: list[str], size: int) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    def _extract_stock(self, *items: dict[str, Any]) -> int | None:
        for item in items:
            stocks = item.get("stocks") or item.get("stock") or {}
            if isinstance(stocks, list):
                values = []
                for stock in stocks:
                    if isinstance(stock, dict):
                        value = stock.get("present") or stock.get("free_to_sell_amount") or stock.get("valid_stock_count")
                        if isinstance(value, int):
                            values.append(value)
                if values:
                    return sum(values)
            if isinstance(stocks, dict):
                for key in ("present", "free_to_sell_amount", "valid_stock_count", "available", "coming"):
                    if isinstance(stocks.get(key), int):
                        return int(stocks[key])
            for key in ("stock", "present", "free_to_sell_amount", "valid_stock_count"):
                if isinstance(item.get(key), int):
                    return int(item[key])
        return None

