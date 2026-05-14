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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application

from app.config import Settings
from app.llm import FreeTheAITextGenerator, OllamaGenerator, TextGenerationError
from app.models import Draft, Product
from app.ozon_client import OzonClient
from app.repository import Repository

logger = logging.getLogger(__name__)

PAGE_SIZE = 8


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

    async def sync_products(self) -> int:
        limit = self._get_int_setting("max_products_per_sync", self.settings.max_products_per_sync)
        products = await self.ozon.fetch_products(limit)
        with self.session_factory() as session:
            repo = Repository(session)
            for product in products:
                repo.upsert_product(product)
        return len(products)

    async def create_next_draft(self) -> Draft | None:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_next_unpublished()
            if product is None:
                return None
            product_id = product.id
        return await self.create_draft_for_product(product_id)

    async def create_draft_for_product(self, product_id: int) -> Draft | None:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None or product.is_excluded:
                return None
            existing = repo.latest_pending_draft(product.id)
            if existing:
                return existing
            product_data = repo.product_to_data(product)

        style = self._get_str_setting("post_style", self.settings.post_style)
        text = await self._generate_post(product_data, style)

        with self.session_factory() as session:
            repo = Repository(session)
            fresh_product = repo.get_product(product_id)
            if fresh_product is None:
                return None
            return repo.create_draft(fresh_product.id, text, style)

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
            price = f", {product.price}" if product.price else ""
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
            text = (
                f"Товар #{product.id}\n"
                f"Статус: {self._product_state(product)}\n"
                f"Название: {product.name}\n"
                f"Артикул: {product.offer_id}\n"
                f"Ozon ID: {product.product_id or '-'}\n"
                f"SKU: {product.sku or '-'}\n"
                f"Бренд: {product.brand or '-'}\n"
                f"Категория: {product.category or '-'}\n"
                f"Цена: {product.price or '-'}\n"
                f"Остаток: {product.stock if product.stock is not None else '-'}\n"
                f"Ссылка заказа: {product.order_url or product.url or '-'}\n\n"
                f"Характеристики:\n{attrs_preview}"
            )
            keyboard = [
                [InlineKeyboardButton("Создать черновик", callback_data=f"draft_product:{product.id}")],
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
            public_text = self._normalize_order_text(draft.text, product)
            text = self._prepare_telegram_html(repo, public_text)
            order_markup = self._order_markup(product)

        if self.settings.dry_run:
            await app.bot.send_message(self.settings.telegram_owner_id, f"DRY_RUN: пост не отправлен в канал.\n\n{draft.text}")
        elif len(images) > 1 and self.settings.max_photos_per_post > 1 and not self._has_local_image(images):
            caption, tail = self._split_caption(text)
            media = [
                InputMediaPhoto(media=url, caption=caption if index == 0 else None, parse_mode=ParseMode.HTML)
                for index, url in enumerate(images)
            ]
            try:
                await app.bot.send_media_group(self.settings.telegram_channel_id, media[: self.settings.max_photos_per_post])
                if tail:
                    await self._send_long_text(app, self.settings.telegram_channel_id, tail, order_markup, parse_html=True)
                elif order_markup:
                    await self._send_long_text(app, self.settings.telegram_channel_id, "Заказать можно по кнопке ниже.", order_markup, parse_html=True)
            except BadRequest as exc:
                logger.warning("Telegram could not fetch media group URLs, falling back to first image upload: %s", exc)
                sent = await self._send_photo_safely(app, self.settings.telegram_channel_id, images[0], caption, order_markup, parse_html=True)
                if sent:
                    await self._send_long_text(app, self.settings.telegram_channel_id, tail, parse_html=True)
                else:
                    await self._send_long_text(app, self.settings.telegram_channel_id, text, order_markup, parse_html=True)
        elif images:
            caption, tail = self._split_caption(text)
            sent = await self._send_photo_safely(app, self.settings.telegram_channel_id, images[0], caption, order_markup, parse_html=True)
            if sent:
                await self._send_long_text(app, self.settings.telegram_channel_id, tail, parse_html=True)
            else:
                await self._send_long_text(app, self.settings.telegram_channel_id, text, order_markup, parse_html=True)
        else:
            await self._send_long_text(app, self.settings.telegram_channel_id, text, order_markup, parse_html=True)

        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            product = repo.get_product(draft.product_id) if draft else None
            if draft and product:
                repo.mark_published(product, draft)
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
            repo.reject_draft(draft)

    async def set_product_excluded(self, product_id: int, value: bool) -> bool:
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                return False
            repo.exclude_product(product, value)
            return True

    async def edit_draft(self, draft_id: int, text: str) -> bool:
        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                return False
            draft.text = text
            session.commit()
            return True

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

    def _prepare_telegram_html(self, repo: Repository, text: str) -> str:
        rendered = escape(text)
        for item in repo.list_premium_emojis(include_inactive=False):
            if not item.telegram_custom_emoji_id:
                continue
            replacement = f'<tg-emoji emoji-id="{escape(item.telegram_custom_emoji_id)}">{escape(item.emoji)}</tg-emoji>'
            rendered = rendered.replace(escape(item.emoji), replacement)
        return rendered

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
        return InlineKeyboardMarkup([[InlineKeyboardButton("Заказать", url=url)]])

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
    ) -> None:
        text = text.strip()
        first = True
        while text:
            chunk = text[:4096]
            if len(text) > 4096:
                split_at = chunk.rfind("\n")
                if split_at > 1000:
                    chunk = chunk[:split_at]
            await app.bot.send_message(
                chat_id,
                chunk.strip(),
                reply_markup=reply_markup if first else None,
                parse_mode=ParseMode.HTML if parse_html else None,
            )
            first = False
            text = text[len(chunk) :].strip()

    async def _send_photo_safely(
        self,
        app: Application,
        chat_id: int | str,
        photo_url: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_html: bool = False,
    ) -> bool:
        local_path = Path(photo_url)
        if local_path.exists() and local_path.is_file():
            try:
                with local_path.open("rb") as image_file:
                    await app.bot.send_photo(
                        chat_id=chat_id,
                        photo=image_file,
                        caption=caption,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML if parse_html else None,
                    )
                return True
            except TelegramError as exc:
                logger.warning("Telegram local photo upload failed: %s", exc)
                return False

        try:
            await app.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML if parse_html else None,
            )
            return True
        except BadRequest as exc:
            logger.warning("Telegram could not fetch photo URL, trying manual upload: %s", exc)

        image = await self._download_image(photo_url)
        if image is None:
            return False

        try:
            await app.bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML if parse_html else None,
            )
            return True
        except TelegramError as exc:
            logger.warning("Telegram photo upload fallback failed: %s", exc)
            return False

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
