from __future__ import annotations

import json
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application

from app.config import Settings
from app.llm import OllamaGenerator
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
        products = await self.ozon.fetch_products(self.settings.max_products_per_sync)
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

        text = await self.generator.generate_post(product_data, self.settings.post_style)

        with self.session_factory() as session:
            repo = Repository(session)
            fresh_product = repo.get_product(product_id)
            if fresh_product is None:
                return None
            return repo.create_draft(fresh_product.id, text, self.settings.post_style)

    async def sync_and_prepare(self, app: Application) -> None:
        try:
            await self.sync_products()
            draft = await self.create_next_draft()
            if draft is None:
                await app.bot.send_message(self.settings.telegram_owner_id, "Новых товаров для постинга нет.")
                return
            if self.settings.app_mode == "auto":
                await self.publish_draft(app, draft.id)
            else:
                await self.send_draft_to_owner(app, draft.id)
        except Exception:
            logger.exception("Scheduled post preparation failed")
            await app.bot.send_message(self.settings.telegram_owner_id, "Ошибка при подготовке поста. Подробности в логах.")

    def products_view(self, status: str = "new", page: int = 1) -> tuple[str, InlineKeyboardMarkup | None]:
        status = status if status in {"new", "all", "published", "excluded"} else "new"
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
                f"Ссылка: {product.url or '-'}\n\n"
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
            await app.bot.send_photo(
                chat_id=self.settings.telegram_owner_id,
                photo=images[0],
                caption=caption,
                reply_markup=keyboard,
            )
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
            text = draft.text

        if self.settings.dry_run:
            await app.bot.send_message(self.settings.telegram_owner_id, f"DRY_RUN: пост не отправлен в канал.\n\n{text}")
        elif len(images) > 1 and self.settings.max_photos_per_post > 1:
            caption, tail = self._split_caption(text)
            media = [InputMediaPhoto(media=url, caption=caption if index == 0 else None) for index, url in enumerate(images)]
            await app.bot.send_media_group(self.settings.telegram_channel_id, media[: self.settings.max_photos_per_post])
            await self._send_long_text(app, self.settings.telegram_channel_id, tail)
        elif images:
            caption, tail = self._split_caption(text)
            await app.bot.send_photo(self.settings.telegram_channel_id, photo=images[0], caption=caption)
            await self._send_long_text(app, self.settings.telegram_channel_id, tail)
        else:
            await self._send_long_text(app, self.settings.telegram_channel_id, text)

        with self.session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            product = repo.get_product(draft.product_id) if draft else None
            if draft and product:
                repo.mark_published(product, draft)
        await app.bot.send_message(self.settings.telegram_owner_id, f"Опубликовано: черновик #{draft_id}")

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

        text = await self.generator.generate_post(product_data, self.settings.post_style)
        with self.session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise ValueError("Product not found")
            new_draft = repo.create_draft(product.id, text, self.settings.post_style)
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

    def _product_images(self, product: Product) -> list[str]:
        return [url for url in self._load_json_list(product.images_json) if isinstance(url, str)]

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
    ) -> None:
        text = text.strip()
        first = True
        while text:
            chunk = text[:4096]
            if len(text) > 4096:
                split_at = chunk.rfind("\n")
                if split_at > 1000:
                    chunk = chunk[:split_at]
            await app.bot.send_message(chat_id, chunk.strip(), reply_markup=reply_markup if first else None)
            first = False
            text = text[len(chunk) :].strip()

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
