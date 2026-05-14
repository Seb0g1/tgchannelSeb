from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.config import Settings
from app.repository import Repository
from app.service import PostService

logger = logging.getLogger(__name__)


def owner_only(settings: Settings):
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            if not user or user.id != settings.telegram_owner_id:
                if update.effective_message:
                    await update.effective_message.reply_text("Команда доступна только владельцу.")
                return
            return await func(update, context)

        return wrapper

    return decorator


def register_handlers(app: Application, service: PostService, settings: Settings) -> None:
    guard = owner_only(settings)

    @guard
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Бот готов.\n\n"
            "Основное:\n"
            "/run - синхронизация + подготовка поста\n"
            "/sync - забрать товары из Ozon\n"
            "/products [new|all|published|excluded] [страница] - список товаров\n"
            "/product <id> - карточка товара и действия\n"
            "/draft [product_id] - черновик для товара или следующего нового\n"
            "/series [product_id] - A/B серия черновиков для товара или следующего нового\n"
            "/day - показать лучший товар дня\n"
            "/drafts [pending|published|rejected|all] [страница] - список черновиков\n\n"
            "Управление:\n"
            "/publish <draft_id> - опубликовать черновик\n"
            "/edit <draft_id> <текст> - изменить черновик\n"
            "/exclude <product_id> - исключить товар\n"
            "/include <product_id> - вернуть товар\n"
            "/status - настройки"
        )

    @guard
    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            f"Канал: {settings.telegram_channel_id}\n"
            f"Режим: {settings.app_mode}\n"
            f"Стиль: {settings.post_style}\n"
            f"Интервал: {settings.post_interval_minutes} мин.\n"
            f"Модель: {settings.ollama_model}\n"
            f"DRY_RUN: {settings.dry_run}"
        )

    @guard
    async def sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        report = await service.sync_products()
        await update.message.reply_text(
            "Ozon sync done.\n"
            f"Received: {report['received']} / requested {report['requested']}\n"
            f"Saved: {report['saved']}\n"
            f"Skipped volume variants: {report['skipped_variants']}\n"
            f"With stock: {report['with_stock']}"
        )

    @guard
    async def products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        status_arg = context.args[0] if context.args else "new"
        page = _page_from_args(context.args, 1)
        text, keyboard = service.products_view(status_arg, page)
        await update.message.reply_text(text, reply_markup=keyboard)

    @guard
    async def product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        product_id = await _required_int(context.args, update, "Формат: /product <id>")
        if product_id is None:
            return
        text, keyboard = service.product_view(product_id)
        await update.message.reply_text(text, reply_markup=keyboard)

    @guard
    async def draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if context.args:
            product_id = await _required_int(context.args, update, "Формат: /draft [product_id]")
            if product_id is None:
                return
            created = await service.create_draft_for_product(product_id)
        else:
            created = await service.create_next_draft()
        if not created:
            await update.message.reply_text("Нет подходящего товара для черновика.")
            return
        await service.send_draft_to_owner(context.application, created.id)

    @guard
    async def series(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if context.args:
            product_id = await _required_int(context.args, update, "Формат: /series [product_id]")
            if product_id is None:
                return
        else:
            best_product = service.best_product_candidate()
            if best_product is None:
                await update.message.reply_text("Нет подходящего товара для серии.")
                return
            product_id = best_product.id
        drafts = await service.create_draft_series_for_product(product_id)
        if not drafts:
            await update.message.reply_text("Серия черновиков не создана.")
            return
        await update.message.reply_text(f"Серия создана: {', '.join(f'#{draft.id}' for draft in drafts)}")

    @guard
    async def day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        best_product = service.best_product_candidate()
        if best_product is None:
            await update.message.reply_text("Пока не нашёл товар дня.")
            return
        with service.session_factory() as session:
            repo = Repository(session)
            item = service._recommendation_payload(best_product, repo)
        product = item["product"]
        reasons = ", ".join(item["reasons"][:3]) if item.get("reasons") else "нет причин"
        await update.message.reply_text(
            f"Товар дня: #{product['id']} {product['name']}\n"
            f"Цена: {product['price'] or '-'}\n"
            f"Остаток: {product['stock'] if product['stock'] is not None else '-'}\n"
            f"Почему: {reasons}"
        )

    @guard
    async def drafts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        status_arg = context.args[0] if context.args else "pending"
        page = _page_from_args(context.args, 1)
        text, keyboard = service.drafts_view(status_arg, page)
        await update.message.reply_text(text, reply_markup=keyboard)

    @guard
    async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Запускаю синхронизацию и подготовку поста.")
        await service.sync_and_prepare(context.application)

    @guard
    async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        draft_id = await _required_int(context.args, update, "Формат: /publish <draft_id>")
        if draft_id is None:
            return
        await service.publish_draft(context.application, draft_id)

    @guard
    async def edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Формат: /edit <draft_id> <новый текст>")
            return
        try:
            draft_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("ID черновика должен быть числом.")
            return
        text = " ".join(context.args[1:]).strip()
        if await service.edit_draft(draft_id, text):
            await update.message.reply_text(f"Черновик #{draft_id} обновлен.")
        else:
            await update.message.reply_text("Черновик не найден.")

    @guard
    async def exclude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        product_id = await _required_int(context.args, update, "Формат: /exclude <product_id>")
        if product_id is None:
            return
        ok = await service.set_product_excluded(product_id, True)
        await update.message.reply_text("Товар исключен." if ok else "Товар не найден.")

    @guard
    async def include(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        product_id = await _required_int(context.args, update, "Формат: /include <product_id>")
        if product_id is None:
            return
        ok = await service.set_product_excluded(product_id, False)
        await update.message.reply_text("Товар возвращен в очередь." if ok else "Товар не найден.")

    @guard
    async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        parts = query.data.split(":")
        action = parts[0]
        try:
            if action == "publish":
                await service.publish_draft(context.application, int(parts[1]))
                await query.edit_message_reply_markup(reply_markup=None)
            elif action == "regen":
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text("Перегенерирую текст.")
                await service.regenerate_draft(context.application, int(parts[1]))
            elif action == "skip":
                await service.skip_product(int(parts[1]))
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(f"Товар по черновику #{parts[1]} исключен.")
            elif action == "draft_product":
                draft_obj = await service.create_draft_for_product(int(parts[1]))
                if draft_obj:
                    await service.send_draft_to_owner(context.application, draft_obj.id)
                else:
                    await query.message.reply_text("Не получилось создать черновик для товара.")
            elif action == "refresh_price":
                product, price = await service.refresh_public_page_price(int(parts[1]))
                if product is None:
                    await query.message.reply_text("Товар не найден.")
                elif price:
                    await query.message.reply_text(f"Цена страницы обновлена: {price}")
                else:
                    await query.message.reply_text("Цену на странице не удалось определить.")
            elif action == "exclude_product":
                await service.set_product_excluded(int(parts[1]), True)
                await query.message.reply_text("Товар исключен.")
            elif action == "include_product":
                await service.set_product_excluded(int(parts[1]), False)
                await query.message.reply_text("Товар возвращен в очередь.")
            elif action == "show_product":
                text, keyboard = service.product_view(int(parts[1]))
                await query.message.reply_text(text, reply_markup=keyboard)
            elif action == "show_draft":
                await service.send_draft_to_owner(context.application, int(parts[1]))
            elif action == "products_page":
                text, keyboard = service.products_view(parts[1], int(parts[2]))
                await query.message.reply_text(text, reply_markup=keyboard)
            elif action == "drafts_page":
                text, keyboard = service.drafts_view(parts[1], int(parts[2]))
                await query.message.reply_text(text, reply_markup=keyboard)
        except Exception:
            logger.exception("Callback failed")
            await query.message.reply_text("Ошибка обработки действия. Подробности в логах.")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("sync", sync))
    app.add_handler(CommandHandler("products", products))
    app.add_handler(CommandHandler("product", product))
    app.add_handler(CommandHandler("draft", draft))
    app.add_handler(CommandHandler("series", series))
    app.add_handler(CommandHandler("day", day))
    app.add_handler(CommandHandler("drafts", drafts))
    app.add_handler(CommandHandler("run", run))
    app.add_handler(CommandHandler("publish", publish))
    app.add_handler(CommandHandler("edit", edit))
    app.add_handler(CommandHandler("exclude", exclude))
    app.add_handler(CommandHandler("include", include))
    app.add_handler(CallbackQueryHandler(callbacks))


def _page_from_args(args: list[str], index: int) -> int:
    if len(args) <= index:
        return 1
    try:
        return max(1, int(args[index]))
    except ValueError:
        return 1


async def _required_int(args: list[str], update: Update, usage: str) -> int | None:
    if not args:
        await update.message.reply_text(usage)
        return None
    try:
        return int(args[0])
    except ValueError:
        await update.message.reply_text(usage)
        return None
