from __future__ import annotations

import logging
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
        for item in items:
            price_block = item.get("price") if isinstance(item.get("price"), dict) else item
            price = (
                price_block.get("marketing_seller_price")
                or price_block.get("marketing_price")
                or price_block.get("price")
                or price_block.get("old_price")
                or item.get("marketing_seller_price")
            )
            if price not in (None, "", "0", 0):
                return self._format_price(price, price_block.get("currency_code") or item.get("currency_code"))
        return None

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

    def _format_price(self, price: Any, currency: str | None) -> str:
        try:
            value = float(price)
            rendered = f"{value:,.0f}".replace(",", " ") if value.is_integer() else f"{value:,.2f}".replace(",", " ")
        except (TypeError, ValueError):
            rendered = str(price)
        if currency == "RUB" or currency is None:
            return f"{rendered} ₽"
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
