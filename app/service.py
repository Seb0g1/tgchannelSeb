from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from collections.abc import Callable

import httpx
from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application

from app.config import Settings
from app.llm import FreeTheAITextGenerator, OllamaGenerator, OpenRouterTextGenerator, PollinationsTextGenerator, TextGenerationError
from app.models import Draft, Product
from app.ozon_client import OzonClient
from app.repository import Repository
from app.schemas import ProductData

logger = logging.getLogger(__name__)

PAGE_SIZE = 8
DEAD_OPENROUTER_MODELS = {"openrouter/cypher-alpha:free"}


class PostService:
    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        ozon: OzonClient,
        generator: OllamaGenerator,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.ozon = ozon
        self.generator = generator

    async def sync_products(self) -> dict[str, object]:
        configured_limit = self._get_int_setting("max_products_per_sync", self.settings.max_products_per_sync)
        limit = min(1000, max(1, configured_limit))
        products = await self.ozon.fetch_products(limit)
        unique_products, skipped_variants = self._skip_volume_variants(products)
        with self.session_factory() as session:
            repo = Repository(session)
            for product in unique_products:
                repo.upsert_product(product)
        report = {
            "requested": limit,
            "received": len(products),
            "saved": len(unique_products),
            "skipped_variants": len(skipped_variants),
            "active": sum(1 for product in unique_products if product.is_active),
            "with_stock": sum(1 for product in unique_products if (product.stock or 0) > 0),
            "sample_skipped": skipped_variants[:10],
        }
        logger.info(
            "Ozon sync finished: requested=%s received=%s saved=%s skipped_variants=%s",
            report["requested"],
            report["received"],
            report["saved"],
            report["skipped_variants"],
        )
        return report

    def _skip_volume_variants(self, products: list[ProductData]) -> tuple[list[ProductData], list[dict[str, str]]]:
        seen: dict[str, ProductData] = {}
        unique: list[ProductData] = []
        skipped: list[dict[str, str]] = []

        for product in products:
            key = self._variant_family_key(product)
            if not key:
                unique.append(product)
                continue
            original = seen.get(key)
            if original is None:
                seen[key] = product
                unique.append(product)
                continue
            skipped.append(
                {
                    "offer_id": product.offer_id,
                    "name": product.name,
                    "kept_offer_id": original.offer_id,
                    "kept_name": original.name,
                }
            )
        return unique, skipped

    def _variant_family_key(self, product: ProductData) -> str:
        name = self._normalize_variant_text(product.name)
        brand = self._normalize_variant_text(product.brand or self._attribute_value(product, "brand") or "")
        if len(name) < 4:
            return ""
        return f"{brand}|{name}"

    def _normalize_variant_text(self, value: str) -> str:
        text = value.lower().replace("\u0451", "\u0435")
        unit = (
            r"\u043c\u043b|ml|\u043c\u0438\u043b\u043b\u0438\u043b\u0438\u0442\u0440(?:\u0430|\u043e\u0432)?|"
            r"\u043b|l|\u043b\u0438\u0442\u0440(?:\u0430|\u043e\u0432)?|"
            r"\u0433|\u0433\u0440|g|kg|\u043a\u0433|\u0448\u0442|pcs|pieces|"
            r"fl\.?\s*oz|oz|\u0443\u043d\u0446(?:\u0438\u044f|\u0438\u0438|\u0438\u0439)?"
        )
        text = re.sub(rf"\([^)]*(?:{unit})[^)]*\)", " ", text)
        text = re.sub(rf"\b\d+\s*[x\u0445\u00d7]\s*\d+(?:[.,]\d+)?\s*(?:{unit})\b", " ", text)
        text = re.sub(rf"\b\d+(?:[.,]\d+)?\s*(?:{unit})\b", " ", text)
        text = re.sub(r"\b(?:\u043e\u0431\u044a\u0435\u043c|\u043e\u0431\u044c\u0435\u043c|volume|size)\s*[:=-]?\s*\d+(?:[.,]\d+)?\b", " ", text)
        text = re.sub(r"[^a-z\u0430-\u044f0-9]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _attribute_value(self, product: ProductData, attribute_name: str) -> str | None:
        for attribute in product.attributes:
            name = str(attribute.get("name") or attribute.get("attribute_name") or "").lower()
            if attribute_name not in name:
                continue
            values = attribute.get("values") or attribute.get("value")
            if isinstance(values, list) and values:
                first = values[0]
                if isinstance(first, dict):
                    return str(first.get("value") or first.get("name") or "") or None
                return str(first) or None
            if values:
                return str(values)
        return None

    async def create_next_draft(self) -> Draft | None:
        product = self.best_product_candidate()
        if product is None:
            return None
        product_id = product.id
        return await self.create_draft_for_product(product_id)

    def best_product_candidate(self) -> Product | None:
        with self.session_factory() as session:
            repo = Repository(session)
            candidates = repo.list_products("new", limit=1000, offset=0)
            ranked = self._rank_products(candidates, repo)
            return ranked[0] if ranked else None

    async def create_draft_for_product(self, product_id: int, style_override: str | None = None, force_new: bool = False) -> Draft | None:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None or product.is_excluded:
                return None
            style = style_override or self._get_str_setting("post_style", self.settings.post_style)
            existing = None if force_new else repo.latest_pending_draft(product.id, style)
            if existing:
                return existing
            product_data = repo.product_to_data(product)
            public_price = await self._resolve_public_page_price(product_data, product, repo)
            if public_price:
                product_data = product_data.model_copy(update={"page_price": public_price})

        text = await self._generate_post(product_data, style)
        text = self._inject_price_note(text, product_data.page_price or product_data.price)

        with self.session_factory() as session:
            repo = Repository(session)
            fresh_product = repo.get_product(product_id)
            if fresh_product is None:
                return None
            draft = repo.create_draft(fresh_product.id, text, style)
            repo.log_product_event(fresh_product.id, "draft_generated", value=style, note="single")
            return draft

    async def create_draft_series_for_product(self, product_id: int, styles: list[str] | None = None) -> list[Draft]:
        styles = [style for style in (styles or ["premium", "selling", "short"]) if style]
        drafts: list[Draft] = []
        for style in styles[:3]:
            draft = await self.create_draft_for_product(product_id, style_override=style, force_new=True)
            if draft:
                drafts.append(draft)
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product:
                repo.log_product_event(product.id, "series_generated", value=",".join(styles[:3]), note=f"count={len(drafts)}")
        return drafts

    async def refresh_public_page_price(self, product_id: int) -> tuple[Product | None, str | None]:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                return None, None
            product_data = repo.product_to_data(product)

        public_price = await self._resolve_public_page_price(product_data, product, None, force_refresh=True)
        with self.session_factory() as session:
            repo = Repository(session)
            fresh = repo.get_product(product_id)
            if fresh is None:
                return None, public_price
            if public_price:
                repo.update_product_page_price(fresh, public_price)
            repo.log_product_event(fresh.id, "price_refreshed", value=public_price, note="public page")
            return fresh, public_price

    async def _resolve_public_page_price(
        self,
        product_data: ProductData,
        product: Product | None,
        repo: Repository | None,
        force_refresh: bool = False,
    ) -> str | None:
        cached_price = product.page_price if product else product_data.page_price
        cached_checked_at = product.page_price_checked_at if product else None
        if not force_refresh and cached_price:
            if cached_checked_at and (datetime.utcnow() - cached_checked_at).total_seconds() < 3600:
                return cached_price

        page_url = product_data.url or (product.order_url if product else None) or (product.url if product else None)
        live_price = await self.ozon.fetch_public_price(page_url)
        if live_price:
            if repo is not None and product is not None:
                repo.update_product_page_price(product, live_price)
            return live_price
        return cached_price or product_data.price

    async def sync_and_prepare(self, app: Application) -> None:
        try:
            await self.sync_products()
            draft = await self.create_next_draft()
            if draft is None:
                await app.bot.send_message(self.settings.telegram_owner_id, "Новых товаров для постинга нет.")
                return
            mode = self._get_str_setting("app_mode", self.settings.app_mode)
            if mode == "auto":
                await self.publish_draft(app, draft.id)
            else:
                await self.send_draft_to_owner(app, draft.id)
        except Exception:
            logger.exception("Scheduled post preparation failed")
            await app.bot.send_message(self.settings.telegram_owner_id, "Ошибка при подготовке поста. Подробности в логах.")

    def products_view(self, status: str = "new", page: int = 1) -> tuple[str, InlineKeyboardMarkup | None]:
        status = status if status in {"new", "active", "archive", "all", "published", "excluded"} else "new"
        page = max(1, page)
        offset = (page - 1) * PAGE_SIZE
        with self.session_factory() as session:
            repo = Repository(session)
            products = repo.list_products(status, PAGE_SIZE, offset)
            total = repo.count_products(status)

        if not products:
            return f"Товары не найдены. Фильтр: {status}.", None

        lines = [f"Товары: {status}, страница {page}. Всего: {total}\n"]
        keyboard: list[list[InlineKeyboardButton]] = []
        for product in products:
            state = self._product_state(product)
            price = f", {product.page_price or product.price}" if (product.page_price or product.price) else ""
            stock = f", остаток {product.stock}" if product.stock is not None else ""
            lines.append(f"#{product.id} [{state}] {product.name}{price}{stock}")
            keyboard.append([InlineKeyboardButton(f"#{product.id} {self._short(product.name, 38)}", callback_data=f"show_product:{product.id}")])

        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("Назад", callback_data=f"products_page:{status}:{page - 1}"))
        if offset + PAGE_SIZE < total:
            nav.append(InlineKeyboardButton("Дальше", callback_data=f"products_page:{status}:{page + 1}"))
        if nav:
            keyboard.append(nav)
        return "\n".join(lines), InlineKeyboardMarkup(keyboard)

    def product_view(self, product_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                return "Товар не найден.", None

            attrs = self._load_json_list(product.attributes_json)
            attrs_preview = "\n".join(f"- {a.get('name')}: {a.get('value')}" for a in attrs[:8]) or "Нет характеристик."
            display_price = product.page_price or product.price or "-"
            text = (
                f"Товар #{product.id}\n"
                f"Статус: {self._product_state(product)}\n"
                f"Название: {product.name}\n"
                f"Артикул: {product.offer_id}\n"
                f"Ozon ID: {product.product_id or '-'}\n"
                f"SKU: {product.sku or '-'}\n"
                f"Бренд: {product.brand or '-'}\n"
                f"Категория: {product.category or '-'}\n"
                f"Цена: {display_price}\n"
                f"Цена на странице: {product.page_price or '-'}\n"
                f"Остаток: {product.stock if product.stock is not None else '-'}\n"
                f"Ссылка заказа: {product.order_url or product.url or '-'}\n\n"
                f"Характеристики:\n{attrs_preview}"
            )
            keyboard = [
                [InlineKeyboardButton("Создать черновик", callback_data=f"draft_product:{product.id}")],
                [InlineKeyboardButton("Обновить цену страницы", callback_data=f"refresh_price:{product.id}")],
            ]
            if product.is_excluded:
                keyboard.append([InlineKeyboardButton("Вернуть в очередь", callback_data=f"include_product:{product.id}")])
            else:
                keyboard.append([InlineKeyboardButton("Исключить", callback_data=f"exclude_product:{product.id}")])
            return text, InlineKeyboardMarkup(keyboard)

    def drafts_view(self, status: str = "pending", page: int = 1) -> tuple[str, InlineKeyboardMarkup | None]:
        status = status if status in {"pending", "published", "rejected", "all"} else "pending"
        page = max(1, page)
        offset = (page - 1) * PAGE_SIZE
        with self.session_factory() as session:
            repo = Repository(session)
            drafts = repo.list_drafts(status, PAGE_SIZE, offset)
            total = repo.count_drafts(status)
            product_names = {
                draft.product_id: (repo.get_product(draft.product_id).name if repo.get_product(draft.product_id) else "-")
                for draft in drafts
            }

        if not drafts:
            return f"Черновики не найдены. Фильтр: {status}.", None

        lines = [f"Черновики: {status}, страница {page}. Всего: {total}\n"]
        keyboard: list[list[InlineKeyboardButton]] = []
        for draft in drafts:
            product_name = product_names.get(draft.product_id, "-")
            lines.append(f"#{draft.id} [{draft.status}] товар #{draft.product_id}: {self._short(product_name, 55)}")
            keyboard.append([InlineKeyboardButton(f"Открыть черновик #{draft.id}", callback_data=f"show_draft:{draft.id}")])

        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("Назад", callback_data=f"drafts_page:{status}:{page - 1}"))
        if offset + PAGE_SIZE < total:
            nav.append(InlineKeyboardButton("Дальше", callback_data=f"drafts_page:{status}:{page + 1}"))
        if nav:
            keyboard.append(nav)
        return "\n".join(lines), InlineKeyboardMarkup(keyboard)

    async def send_draft_to_owner(self, app: Application, draft_id: int) -> None:
        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                return
            product = repo.get_product(draft.product_id)
            if product is None:
                return
            images = self._product_images(product)
            text = self._draft_preview(draft, product)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Опубликовать", callback_data=f"publish:{draft_id}"),
                    InlineKeyboardButton("Заново", callback_data=f"regen:{draft_id}"),
                ],
                [InlineKeyboardButton("Пропустить товар", callback_data=f"skip:{draft_id}")],
            ]
        )
        if images:
            caption, tail = self._split_caption(text)
            sent = await self._send_photo_safely(
                app,
                self.settings.telegram_owner_id,
                images[0],
                caption,
                keyboard,
            )
            if not sent:
                await self._send_long_text(app, self.settings.telegram_owner_id, text, keyboard)
                return
            if tail:
                await self._send_long_text(app, self.settings.telegram_owner_id, tail, keyboard)
        else:
            await self._send_long_text(app, self.settings.telegram_owner_id, text, keyboard)

    async def publish_draft(self, app: Application, draft_id: int) -> None:
        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                raise ValueError("Draft not found")
            product = repo.get_product(draft.product_id)
            if product is None:
                raise ValueError("Product not found")
            images = self._product_images(product)
            public_text = self._strip_markdown(draft.text)
            public_text = self._normalize_price_text(public_text, product)
            public_text = self._normalize_order_text(public_text, product)
            text = self._prepare_telegram_html(repo, public_text)
            order_markup = self._order_markup(product)

        sent_message_id: int | None = None
        if self.settings.dry_run:
            await app.bot.send_message(self.settings.telegram_owner_id, f"DRY_RUN: пост не отправлен в канал.\n\n{draft.text}")
        elif len(images) > 1 and self.settings.max_photos_per_post > 1 and not self._has_local_image(images):
            caption, tail = self._split_caption(text)
            media = [
                InputMediaPhoto(media=url, caption=caption if index == 0 else None, parse_mode=ParseMode.HTML)
                for index, url in enumerate(images)
            ]
            try:
                sent_group = await app.bot.send_media_group(
                    self.settings.telegram_channel_id,
                    media[: self.settings.max_photos_per_post],
                )
                if sent_group:
                    sent_message_id = sent_group[0].message_id
                if tail:
                    sent_tail = await self._send_long_text(
                        app,
                        self.settings.telegram_channel_id,
                        tail,
                        order_markup,
                        parse_html=True,
                    )
                    sent_message_id = sent_message_id or (sent_tail.message_id if sent_tail else None)
                elif order_markup:
                    sent_tail = await self._send_long_text(
                        app,
                        self.settings.telegram_channel_id,
                        "Заказать можно по кнопке ниже.",
                        order_markup,
                        parse_html=True,
                    )
                    sent_message_id = sent_message_id or (sent_tail.message_id if sent_tail else None)
            except BadRequest as exc:
                logger.warning("Telegram could not fetch media group URLs, falling back to first image upload: %s", exc)
                sent = await self._send_photo_safely(app, self.settings.telegram_channel_id, images[0], caption, order_markup, parse_html=True)
                if sent:
                    sent_message_id = sent.message_id
                    sent_tail = await self._send_long_text(app, self.settings.telegram_channel_id, tail, parse_html=True)
                    sent_message_id = sent_message_id or (sent_tail.message_id if sent_tail else None)
                else:
                    sent_text = await self._send_long_text(app, self.settings.telegram_channel_id, text, order_markup, parse_html=True)
                    sent_message_id = sent_text.message_id if sent_text else None
        elif images:
            caption, tail = self._split_caption(text)
            sent = await self._send_photo_safely(app, self.settings.telegram_channel_id, images[0], caption, order_markup, parse_html=True)
            if sent:
                sent_message_id = sent.message_id
                sent_tail = await self._send_long_text(app, self.settings.telegram_channel_id, tail, parse_html=True)
                sent_message_id = sent_message_id or (sent_tail.message_id if sent_tail else None)
            else:
                sent_text = await self._send_long_text(app, self.settings.telegram_channel_id, text, order_markup, parse_html=True)
                sent_message_id = sent_text.message_id if sent_text else None
        else:
            sent_text = await self._send_long_text(app, self.settings.telegram_channel_id, text, order_markup, parse_html=True)
            sent_message_id = sent_text.message_id if sent_text else None

        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            product = repo.get_product(draft.product_id) if draft else None
            if draft and product:
                repo.mark_published(product, draft, sent_message_id)
        await app.bot.send_message(self.settings.telegram_owner_id, f"Опубликовано: черновик #{draft_id}")

    async def process_scheduled_posts(self, app: Application) -> None:
        with self.session_factory() as session:
            repo = Repository(session)
            due_items = repo.due_scheduled_posts(datetime.utcnow(), limit=5)
            due = [(item.id, item.draft_id) for item in due_items]

        for scheduled_id, draft_id in due:
            try:
                await self.publish_draft(app, draft_id)
            except Exception:
                logger.exception("Scheduled publication failed: schedule=%s draft=%s", scheduled_id, draft_id)
                with self.session_factory() as session:
                    repo = Repository(session)
                    item = repo.get_scheduled_post(scheduled_id)
                    if item:
                        repo.update_scheduled_status(item, "failed")
                continue

            with self.session_factory() as session:
                repo = Repository(session)
                item = repo.get_scheduled_post(scheduled_id)
                if item:
                    repo.update_scheduled_status(item, "published")

    async def regenerate_draft(self, app: Application, draft_id: int) -> int:
        with self.session_factory() as session:
            repo = Repository(session)
            old_draft = repo.get_draft(draft_id)
            if old_draft is None:
                raise ValueError("Draft not found")
            product = repo.get_product(old_draft.product_id)
            if product is None:
                raise ValueError("Product not found")
            product_id = product.id
            product_data = repo.product_to_data(product)
            repo.reject_draft(old_draft)

        style = self._get_str_setting("post_style", self.settings.post_style)
        text = await self._generate_post(product_data, style)
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise ValueError("Product not found")
            new_draft = repo.create_draft(product.id, text, style)
            repo.log_product_event(product.id, "draft_generated", value=style, note="regenerated")
        await self.send_draft_to_owner(app, new_draft.id)
        return new_draft.id

    async def skip_product(self, draft_id: int) -> None:
        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                return
            product = repo.get_product(draft.product_id)
            if product:
                repo.exclude_product(product, True)
                repo.log_product_event(product.id, "excluded", note="manual skip")
            repo.reject_draft(draft)

    async def set_product_excluded(self, product_id: int, value: bool) -> bool:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                return False
            repo.exclude_product(product, value)
            repo.log_product_event(product.id, "excluded" if value else "included", note="manual toggle")
            return True

    async def edit_draft(self, draft_id: int, text: str) -> bool:
        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                return False
            draft.text = text
            session.commit()
            repo.log_product_event(draft.product_id, "draft_edited", note=f"draft={draft.id}")
            return True

    def recommendation_cards(self, limit: int = 3) -> list[dict[str, object]]:
        with self.session_factory() as session:
            repo = Repository(session)
            candidates = repo.list_products("new", limit=1000, offset=0)
            ranked = self._rank_products(candidates, repo)[:limit]
            return [self._recommendation_payload(product, repo) for product in ranked]

    def product_insights(self, product_id: int) -> dict[str, object] | None:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                return None
            events = repo.count_product_events(product_id)
            drafts = repo.list_drafts("all", limit=200)
            product_drafts = [draft for draft in drafts if draft.product_id == product.id]
            recommended = self._recommendation_payload(product, repo)
            return {
                "product": self._product_brief(product),
                "events": events,
                "drafts_count": len(product_drafts),
                "recommended": recommended,
                "timeline": [
                    {
                        "event_type": item.event_type,
                        "value": item.value,
                        "note": item.note,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                    }
                    for item in repo.list_product_events(product_id, limit=12)
                ],
            }

    async def _generate_post(self, product_data, style: str) -> str:
        engine = self._get_str_setting("text_engine", self.settings.text_engine)
        if engine == "freetheai":
            generator = FreeTheAITextGenerator(
                api_key=self._get_str_setting("freetheai_api_key", self.settings.freetheai_api_key or ""),
                base_url=self._get_str_setting("freetheai_base_url", self.settings.freetheai_base_url),
                model=self._get_str_setting("freetheai_text_model", self.settings.freetheai_text_model),
                timeout_seconds=self._get_int_setting(
                    "freetheai_text_timeout_seconds",
                    self.settings.freetheai_text_timeout_seconds,
                ),
                max_tokens=self._get_int_setting("freetheai_text_max_tokens", self.settings.freetheai_text_max_tokens),
            )
            try:
                return await generator.generate_post(product_data, style)
            except TextGenerationError:
                raise
        if engine == "pollinations":
            generator = PollinationsTextGenerator(
                api_key=self._get_str_setting("pollinations_api_key", self.settings.pollinations_api_key or ""),
                base_url=self._get_str_setting("pollinations_base_url", self.settings.pollinations_base_url),
                model=self._get_str_setting("pollinations_text_model", self.settings.pollinations_text_model),
                timeout_seconds=self._get_int_setting(
                    "pollinations_text_timeout_seconds",
                    self.settings.pollinations_text_timeout_seconds,
                ),
                max_tokens=self._get_int_setting("pollinations_text_max_tokens", self.settings.pollinations_text_max_tokens),
            )
            try:
                return await generator.generate_post(product_data, style)
            except TextGenerationError:
                raise
        if engine == "openrouter":
            model = self._get_str_setting("openrouter_text_model", self.settings.openrouter_text_model)
            if model in DEAD_OPENROUTER_MODELS:
                model = "openrouter/free"
            generator = OpenRouterTextGenerator(
                api_key=self._get_str_setting("openrouter_api_key", self.settings.openrouter_api_key or ""),
                base_url=self._get_str_setting("openrouter_base_url", self.settings.openrouter_base_url),
                model=model,
                timeout_seconds=self._get_int_setting(
                    "openrouter_text_timeout_seconds",
                    self.settings.openrouter_text_timeout_seconds,
                ),
                max_tokens=self._get_int_setting("openrouter_text_max_tokens", self.settings.openrouter_text_max_tokens),
                site_url=self._get_str_setting("openrouter_site_url", self.settings.openrouter_site_url or ""),
                site_name=self._get_str_setting("openrouter_site_name", self.settings.openrouter_site_name),
            )
            try:
                return await generator.generate_post(product_data, style)
            except TextGenerationError:
                raise

        model = self._get_str_setting("ollama_model", self.settings.ollama_model)
        self.generator.model = model
        self.generator.timeout_seconds = self._get_int_setting("ollama_timeout_seconds", self.settings.ollama_timeout_seconds)
        self.generator.num_predict = self._get_int_setting("ollama_num_predict", self.settings.ollama_num_predict)
        return await self.generator.generate_post(product_data, style)

    def _get_str_setting(self, key: str, default: str) -> str:
        with self.session_factory() as session:
            repo = Repository(session)
            return repo.get_setting(key, default) or default

    def _get_int_setting(self, key: str, default: int) -> int:
        value = self._get_str_setting(key, str(default))
        try:
            return int(value)
        except ValueError:
            return default

    def _rank_products(self, products: list[Product], repo: Repository) -> list[Product]:
        def score(product: Product) -> tuple[float, list[str]]:
            events = repo.count_product_events(product.id)
            reasons: list[str] = []
            value = 0.0
            if product.is_active and not product.is_excluded:
                value += 35
                reasons.append("active")
            if not product.is_published:
                value += 22
                reasons.append("fresh")
            stock = product.stock or 0
            if stock > 0:
                stock_bonus = min(stock, 50) * 2
                value += stock_bonus
                reasons.append(f"stock {stock}")
            price_value = self._parse_price_value(product.page_price or product.price)
            if price_value is not None:
                if price_value <= 5000:
                    value += 18
                    reasons.append("good price")
                elif price_value <= 10000:
                    value += 10
                    reasons.append("balanced price")
            if product.styled_image_path:
                value += 15
                reasons.append("premium image ready")
            elif product.images_json and product.images_json != "[]":
                value += 5
                reasons.append("has source photo")
            if product.updated_at:
                age_days = max(0, (datetime.utcnow() - product.updated_at).days)
                freshness = max(0, 18 - age_days)
                value += freshness
                if freshness:
                    reasons.append("recently updated")
            value += min(events.get("draft_generated", 0), 5) * 2
            if events.get("published"):
                value -= 50
            return value, reasons

        scored = [(product, *score(product)) for product in products]
        scored.sort(key=lambda item: item[1], reverse=True)
        return [item[0] for item in scored]

    def _recommendation_payload(self, product: Product, repo: Repository) -> dict[str, object]:
        events = repo.count_product_events(product.id)
        score, reasons = self._score_product(product, events)
        return {
            "product": self._product_brief(product),
            "score": round(score, 2),
            "reasons": reasons,
            "events": events,
        }

    def _score_product(self, product: Product, events: dict[str, int]) -> tuple[float, list[str]]:
        reasons: list[str] = []
        value = 0.0
        if product.is_active and not product.is_excluded:
            value += 35
            reasons.append("active")
        if not product.is_published:
            value += 22
            reasons.append("ready for post")
        stock = product.stock or 0
        if stock > 0:
            stock_bonus = min(stock, 50) * 2
            value += stock_bonus
            reasons.append(f"stock {stock}")
        price_value = self._parse_price_value(product.page_price or product.price)
        if price_value is not None:
            if price_value <= 5000:
                value += 18
                reasons.append("nice price")
            elif price_value <= 10000:
                value += 10
                reasons.append("mid price")
        if product.styled_image_path:
            value += 15
            reasons.append("premium image")
        elif product.images_json and product.images_json != "[]":
            value += 5
            reasons.append("source photo")
        if product.updated_at:
            age_days = max(0, (datetime.utcnow() - product.updated_at).days)
            freshness = max(0, 18 - age_days)
            value += freshness
            if freshness:
                reasons.append("recently refreshed")
        value += min(events.get("draft_generated", 0), 5) * 2
        value += min(events.get("image_generated", 0), 3) * 1.5
        if events.get("published"):
            value -= 50
        return value, reasons

    def _parse_price_value(self, value: str | None) -> float | None:
        if not value:
            return None
        text = str(value).replace("\xa0", " ")
        match = re.search(r"(\d[\d\s]*(?:[.,]\d+)?)", text)
        if not match:
            return None
        raw = match.group(1).replace(" ", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None

    def _product_brief(self, product: Product) -> dict[str, object]:
        return {
            "id": product.id,
            "offer_id": product.offer_id,
            "name": product.name,
            "brand": product.brand,
            "price": product.page_price or product.price,
            "api_price": product.price,
            "page_price": product.page_price,
            "stock": product.stock,
            "is_active": product.is_active,
            "is_published": product.is_published,
            "styled_image_path": product.styled_image_path,
        }

    def _prepare_telegram_html(self, repo: Repository, text: str) -> str:
        rendered = escape(self._strip_markdown(text))
        for item in repo.list_premium_emojis(include_inactive=False):
            if not item.telegram_custom_emoji_id:
                continue
            replacement = f'<tg-emoji emoji-id="{escape(item.telegram_custom_emoji_id)}">{escape(item.emoji)}</tg-emoji>'
            rendered = rendered.replace(escape(item.emoji), replacement)
        return rendered

    def _inject_price_note(self, text: str, price: str | None) -> str:
        if not price:
            return text.strip()
        disclaimer = "Цена может отличаться, проверяйте у себя!"
        working = text.strip()
        price_pattern = re.compile(r"(?im)^\s*(?:[-–—•]\s*)?(?:цена|стоимость|от)\s*[:：-]\s*.*$")
        if price_pattern.search(working):
            working = price_pattern.sub(f"от: {price}", working, count=1)
        else:
            working = self._insert_before_hashtags(working, f"от: {price}")
        if disclaimer.lower() not in working.lower():
            working = self._insert_before_hashtags(working, disclaimer)
        return re.sub(r"\n{3,}", "\n\n", working).strip()

    def _insert_before_hashtags(self, text: str, addition: str) -> str:
        hashtag_match = re.search(r"(\n[#\wА-Яа-яЁё][^\n]*(?:\n[#\wА-Яа-яЁё][^\n]*)*)\s*$", text)
        if hashtag_match:
            start = hashtag_match.start(1)
            head = text[:start].rstrip()
            tail = text[start:].lstrip()
            return f"{head}\n\n{addition}\n\n{tail}".strip()
        return f"{text.rstrip()}\n\n{addition}".strip()

    def _strip_markdown(self, text: str) -> str:
        cleaned = re.sub(r"^#{1,6}\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"__(.*?)__", r"\1", cleaned)
        cleaned = re.sub(r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)", r"\1", cleaned)
        cleaned = re.sub(r"(?<!_)_(?!\s)(.*?)(?<!\s)_(?!_)", r"\1", cleaned)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        return cleaned.replace("**", "").replace("__", "").strip()

    def _normalize_price_text(self, text: str, product: Product) -> str:
        price = self._format_price(product.page_price or product.price)
        if not price:
            return text
        return self._inject_price_note(text, price)

    def _normalize_order_text(self, text: str, product: Product) -> str:
        url = product.order_url or product.url
        if not url:
            return text
        normalized = text.replace(url, "").strip()
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        if "кнопк" not in normalized.lower():
            hashtag_match = re.search(r"(\n[#\wа-яА-ЯёЁ\s#]+)$", normalized)
            phrase = "Заказать можно по кнопке ниже."
            if hashtag_match:
                start = hashtag_match.start(1)
                normalized = f"{normalized[:start].rstrip()}\n\n{phrase}{normalized[start:]}"
            else:
                normalized = f"{normalized}\n\n{phrase}"
        return normalized.strip()

    def _product_images(self, product: Product) -> list[str]:
        images: list[str] = []
        if product.styled_image_path and Path(product.styled_image_path).exists():
            images.append(product.styled_image_path)
        images.extend(url for url in self._load_json_list(product.images_json) if isinstance(url, str) and url.startswith("http"))
        return images

    def _order_markup(self, product: Product) -> InlineKeyboardMarkup | None:
        url = product.order_url or product.url
        if not url or not url.startswith(("http://", "https://")):
            return None
        price = self._format_price(product.page_price or product.price)
        label = f"Заказать · от {price}" if price else "Заказать"
        return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])

    def _format_price(self, value: str | int | float | None) -> str | None:
        if value in (None, "", 0, "0"):
            return None
        text = str(value).strip()
        if "\u20bd" in text or "руб" in text.lower():
            return re.sub(r"\s+", " ", text)
        raw = re.sub(r"[^\d,\.]", "", text)
        if not raw:
            return text
        raw = raw.replace(",", ".")
        try:
            amount = float(raw)
        except ValueError:
            return text
        rendered = f"{amount:,.0f}".replace(",", " ") if amount.is_integer() else f"{amount:,.2f}".replace(",", " ")
        return f"{rendered} \u20bd"

    def _draft_preview(self, draft: Draft, product: Product) -> str:
        return (
            f"Черновик #{draft.id} для товара #{product.id}\n"
            f"{product.name}\n\n"
            f"{draft.text}\n\n"
            f"Для правки отправьте: /edit {draft.id} новый текст"
        )

    def _split_caption(self, text: str) -> tuple[str, str]:
        if len(text) <= 1024:
            return text, ""
        split_at = text.rfind("\n", 0, 1000)
        if split_at < 400:
            split_at = 1000
        return text[:split_at].strip(), text[split_at:].strip()

    async def _send_long_text(
        self,
        app: Application,
        chat_id: int | str,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_html: bool = False,
    ) -> Message | None:
        text = text.strip()
        first_sent: Message | None = None
        first = True
        while text:
            chunk = text[:4096]
            if len(text) > 4096:
                split_at = chunk.rfind("\n")
                if split_at > 1000:
                    chunk = chunk[:split_at]
            sent = await app.bot.send_message(
                chat_id,
                chunk.strip(),
                reply_markup=reply_markup if first else None,
                parse_mode=ParseMode.HTML if parse_html else None,
            )
            first_sent = first_sent or sent
            first = False
            text = text[len(chunk) :].strip()
        return first_sent

    async def _send_photo_safely(
        self,
        app: Application,
        chat_id: int | str,
        photo_url: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_html: bool = False,
    ) -> Message | None:
        local_path = Path(photo_url)
        if local_path.exists() and local_path.is_file():
            try:
                with local_path.open("rb") as image_file:
                    sent = await app.bot.send_photo(
                        chat_id=chat_id,
                        photo=image_file,
                        caption=caption,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML if parse_html else None,
                    )
                return sent
            except TelegramError as exc:
                logger.warning("Telegram local photo upload failed: %s", exc)
                return None

        try:
            sent = await app.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML if parse_html else None,
            )
            return sent
        except BadRequest as exc:
            logger.warning("Telegram could not fetch photo URL, trying manual upload: %s", exc)

        image = await self._download_image(photo_url)
        if image is None:
            return None

        try:
            sent = await app.bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML if parse_html else None,
            )
            return sent
        except TelegramError as exc:
            logger.warning("Telegram photo upload fallback failed: %s", exc)
            return None

    async def _download_image(self, url: str) -> BytesIO | None:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; tgchannelSeb/1.0)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=True, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "image" not in content_type:
                    logger.warning("URL did not return an image: %s (%s)", url, content_type)
                    return None
                image = BytesIO(response.content)
                image.name = "product.jpg"
                image.seek(0)
                return image
        except httpx.HTTPError as exc:
            logger.warning("Could not download product image %s: %s", url, exc)
            return None

    def _has_local_image(self, images: list[str]) -> bool:
        return any(Path(image).exists() and Path(image).is_file() for image in images)

    def _product_state(self, product: Product) -> str:
        if product.is_excluded:
            return "excluded"
        if product.is_published:
            return "published"
        return "new"

    def _load_json_list(self, value: str) -> list:
        try:
            loaded = json.loads(value or "[]")
            return loaded if isinstance(loaded, list) else []
        except json.JSONDecodeError:
            return []

    def _short(self, text: str, limit: int) -> str:
        text = text.replace("\n", " ").strip()
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
