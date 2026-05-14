from __future__ import annotations

import secrets
import time
import hmac
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace

import uvicorn
from fastapi import Body, Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from telegram import Bot

from app.config import Settings, get_settings
from app.image_styler import HuggingFaceImageStyler, ImageGenerationError
from app.llm import OllamaGenerator
from app.logging_config import setup_logging
from app.models import Draft, PremiumEmoji, Product, make_session_factory
from app.ozon_client import OzonClient
from app.repository import Repository
from app.service import PostService

SESSION_COOKIE = "aromat_session"


class ProductUpdate(BaseModel):
    order_url: str | None = None
    is_active: bool = True
    is_excluded: bool = False


class EmojiCreate(BaseModel):
    label: str
    emoji: str
    telegram_custom_emoji_id: str | None = None
    description: str | None = None


class DraftUpdate(BaseModel):
    text: str


class LoginPayload(BaseModel):
    username: str
    password: str


class AppSettingsPayload(BaseModel):
    app_mode: str
    post_style: str
    max_products_per_sync: int
    post_interval_minutes: int
    ollama_model: str
    ollama_timeout_seconds: int
    ollama_num_predict: int
    image_engine: str = "none"
    comfyui_base_url: str = "http://127.0.0.1:8188"
    hf_image_model: str = "stabilityai/stable-diffusion-xl-refiner-1.0"
    hf_image_provider: str = "auto"
    hf_image_width: int = 1024
    hf_image_height: int = 1280
    image_generation_mode: str = "image_to_image"


class ScheduleCreate(BaseModel):
    draft_id: int
    scheduled_at: datetime


def create_session_token(username: str, settings: Settings) -> str:
    expires_at = int(time.time()) + 60 * 60 * 24 * 7
    payload = f"{username}:{expires_at}"
    signature = hmac.new(settings.web_session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_session_token(token: str | None, settings: Settings) -> str | None:
    if not token:
        return None
    parts = token.split(":")
    if len(parts) != 3:
        return None
    username, raw_expires_at, signature = parts
    payload = f"{username}:{raw_expires_at}"
    expected = hmac.new(settings.web_session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        if int(raw_expires_at) < int(time.time()):
            return None
    except ValueError:
        return None
    return username


def require_admin(
    aromat_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    settings: Settings = Depends(get_settings),
) -> str:
    username = verify_session_token(aromat_session, settings)
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return username


def product_payload(product: Product) -> dict:
    return {
        "id": product.id,
        "offer_id": product.offer_id,
        "product_id": product.product_id,
        "sku": product.sku,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "description": product.description,
        "price": product.price,
        "stock": product.stock,
        "url": product.url,
        "order_url": product.order_url,
        "visibility": product.visibility,
        "is_active": product.is_active,
        "is_excluded": product.is_excluded,
        "is_published": product.is_published,
        "styled_image_path": product.styled_image_path,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }


def draft_payload(draft: Draft) -> dict:
    return {
        "id": draft.id,
        "product_id": draft.product_id,
        "text": draft.text,
        "status": draft.status,
        "style": draft.style,
        "telegram_message_id": draft.telegram_message_id,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def emoji_payload(emoji: PremiumEmoji) -> dict:
    return {
        "id": emoji.id,
        "label": emoji.label,
        "emoji": emoji.emoji,
        "telegram_custom_emoji_id": emoji.telegram_custom_emoji_id,
        "description": emoji.description,
        "is_active": emoji.is_active,
        "created_at": emoji.created_at.isoformat() if emoji.created_at else None,
    }


def scheduled_payload(item) -> dict:
    return {
        "id": item.id,
        "draft_id": item.draft_id,
        "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def create_web_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    session_factory = make_session_factory(settings.database_url)
    ozon = OzonClient(
        settings.ozon_client_id,
        settings.ozon_api_key,
        settings.ozon_base_url,
        visibility=settings.ozon_visibility,
    )
    generator = OllamaGenerator(
        settings.ollama_base_url,
        settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
        num_predict=settings.ollama_num_predict,
    )
    post_service = PostService(settings, session_factory, ozon, generator)
    app = FastAPI(title="Aromat Day Admin API")

    @app.post("/api/auth/login")
    async def login(payload: LoginPayload, response: Response):
        valid_username = secrets.compare_digest(payload.username, settings.web_admin_username)
        valid_password = secrets.compare_digest(payload.password, settings.web_admin_password)
        if not (valid_username and valid_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        token = create_session_token(payload.username, settings)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )
        return {"ok": True}

    @app.post("/api/auth/logout")
    async def logout(response: Response):
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    async def me(_: str = Depends(require_admin)):
        return {"name": "Аромат дня", "channel": settings.telegram_channel_id}

    @app.get("/api/settings")
    async def get_app_settings(_: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            db = repo.get_settings_map()
        return {
            "app_mode": db.get("app_mode", settings.app_mode),
            "post_style": db.get("post_style", settings.post_style),
            "max_products_per_sync": int(db.get("max_products_per_sync", settings.max_products_per_sync)),
            "post_interval_minutes": int(db.get("post_interval_minutes", settings.post_interval_minutes)),
            "ollama_model": db.get("ollama_model", settings.ollama_model),
            "ollama_timeout_seconds": int(db.get("ollama_timeout_seconds", settings.ollama_timeout_seconds)),
            "ollama_num_predict": int(db.get("ollama_num_predict", settings.ollama_num_predict)),
            "image_engine": db.get("image_engine", settings.image_engine),
            "comfyui_base_url": db.get("comfyui_base_url", settings.comfyui_base_url),
            "hf_image_model": db.get("hf_image_model", settings.hf_image_model),
            "hf_image_provider": db.get("hf_image_provider", settings.hf_image_provider),
            "hf_image_width": int(db.get("hf_image_width", settings.hf_image_width)),
            "hf_image_height": int(db.get("hf_image_height", settings.hf_image_height)),
            "image_generation_mode": db.get("image_generation_mode", settings.image_generation_mode),
        }

    @app.patch("/api/settings")
    async def update_app_settings(payload: AppSettingsPayload, _: str = Depends(require_admin)):
        values = payload.model_dump()
        with session_factory() as session:
            repo = Repository(session)
            for key, value in values.items():
                repo.set_setting(key, str(value))
        return values

    @app.get("/api/dashboard")
    async def dashboard(_: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            counts = repo.dashboard_counts()
            products, _total = repo.search_products(status="new", limit=8)
            drafts = repo.list_drafts("pending", limit=8)
        return {
            "counts": counts,
            "products": [product_payload(item) for item in products],
            "drafts": [draft_payload(item) for item in drafts],
        }

    @app.post("/api/sync")
    async def sync_products(_: str = Depends(require_admin)):
        count = await post_service.sync_products()
        return {"count": count}

    @app.get("/api/products")
    async def products(
        q: str = "",
        status_filter: str = "active",
        page: int = 1,
        limit: int = 40,
        _: str = Depends(require_admin),
    ):
        page = max(1, page)
        limit = min(max(1, limit), 100)
        offset = (page - 1) * limit
        with session_factory() as session:
            repo = Repository(session)
            items, total = repo.search_products(q, status_filter, limit, offset)
        return {
            "items": [product_payload(item) for item in items],
            "total": total,
            "page": page,
            "limit": limit,
        }

    @app.get("/api/products/{product_id}")
    async def product_detail(product_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            attrs = repo.product_to_data(product).attributes
            drafts = [draft for draft in repo.list_drafts("all", limit=50) if draft.product_id == product.id]
        return {
            "product": product_payload(product),
            "attributes": attrs,
            "drafts": [draft_payload(item) for item in drafts],
        }

    @app.patch("/api/products/{product_id}")
    async def update_product(product_id: int, payload: ProductUpdate = Body(...), _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            repo.update_product_admin_fields(product, payload.order_url, payload.is_active, payload.is_excluded)
            return product_payload(product)

    @app.post("/api/products/{product_id}/draft")
    async def create_draft(product_id: int, _: str = Depends(require_admin)):
        draft = await post_service.create_draft_for_product(product_id)
        if draft is None:
            raise HTTPException(status_code=400, detail="Draft was not created")
        return draft_payload(draft)

    @app.get("/api/drafts")
    async def drafts(status_filter: str = "pending", page: int = 1, limit: int = 30, _: str = Depends(require_admin)):
        page = max(1, page)
        limit = min(max(1, limit), 100)
        offset = (page - 1) * limit
        with session_factory() as session:
            repo = Repository(session)
            items = repo.list_drafts(status_filter, limit, offset)
            total = repo.count_drafts(status_filter)
        return {
            "items": [draft_payload(item) for item in items],
            "total": total,
            "page": page,
            "limit": limit,
        }

    @app.get("/api/drafts/{draft_id}")
    async def draft_detail(draft_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft not found")
            product = repo.get_product(draft.product_id)
        return {
            "draft": draft_payload(draft),
            "product": product_payload(product) if product else None,
        }

    @app.patch("/api/drafts/{draft_id}")
    async def update_draft(draft_id: int, payload: DraftUpdate, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft not found")
            repo.update_draft_text(draft, payload.text)
            return draft_payload(draft)

    @app.post("/api/drafts/{draft_id}/publish")
    async def publish_draft(draft_id: int, _: str = Depends(require_admin)):
        bot = Bot(settings.telegram_bot_token)
        await post_service.publish_draft(SimpleNamespace(bot=bot), draft_id)
        return {"ok": True}

    @app.post("/api/drafts/{draft_id}/reject")
    async def reject_draft(draft_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft not found")
            repo.reject_draft(draft)
            return draft_payload(draft)

    @app.get("/api/schedule")
    async def schedule(_: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            items = repo.list_scheduled_posts("all", limit=200)
        return {"items": [scheduled_payload(item) for item in items]}

    @app.post("/api/schedule")
    async def create_schedule(payload: ScheduleCreate, _: str = Depends(require_admin)):
        scheduled_at = payload.scheduled_at
        if scheduled_at.tzinfo is not None:
            scheduled_at = scheduled_at.astimezone(timezone.utc).replace(tzinfo=None)
        with session_factory() as session:
            repo = Repository(session)
            if repo.get_draft(payload.draft_id) is None:
                raise HTTPException(status_code=404, detail="Draft not found")
            item = repo.create_scheduled_post(payload.draft_id, scheduled_at)
        return scheduled_payload(item)

    @app.delete("/api/schedule/{scheduled_id}")
    async def delete_schedule(scheduled_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            ok = repo.delete_scheduled_post(scheduled_id)
        return {"ok": ok}

    @app.post("/api/products/{product_id}/premium-image")
    async def generate_premium_image(product_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            engine = repo.get_setting("image_engine", settings.image_engine)
            if engine == "huggingface":
                dynamic_settings = settings.model_copy(
                    update={
                        "hf_image_model": repo.get_setting("hf_image_model", settings.hf_image_model),
                        "hf_image_provider": repo.get_setting("hf_image_provider", settings.hf_image_provider),
                        "hf_image_width": int(repo.get_setting("hf_image_width", str(settings.hf_image_width))),
                        "hf_image_height": int(repo.get_setting("hf_image_height", str(settings.hf_image_height))),
                        "image_generation_mode": repo.get_setting("image_generation_mode", settings.image_generation_mode),
                    }
                )
                styler = HuggingFaceImageStyler(dynamic_settings)
                try:
                    image_path = await styler.generate(product)
                except ImageGenerationError as exc:
                    return {"status": "failed", "message": str(exc), "product": product_payload(product)}
                repo.update_product_styled_image(product, image_path)
                return {"status": "generated", "message": "Premium image generated.", "product": product_payload(product)}
            if engine != "comfyui":
                return {
                    "status": "not_configured",
                    "message": "Set image_engine=huggingface in settings before generation.",
                    "product": product_payload(product),
                }
        return {"status": "queued", "message": "ComfyUI integration placeholder is ready for workflow wiring."}

    @app.get("/api/emojis")
    async def emojis(_: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            items = repo.list_premium_emojis()
        return {"items": [emoji_payload(item) for item in items]}

    @app.post("/api/emojis")
    async def create_emoji(payload: EmojiCreate, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            item = repo.create_premium_emoji(
                payload.label.strip(),
                payload.emoji.strip(),
                payload.telegram_custom_emoji_id.strip() if payload.telegram_custom_emoji_id else None,
                payload.description.strip() if payload.description else None,
            )
        return emoji_payload(item)

    @app.delete("/api/emojis/{emoji_id}")
    async def delete_emoji(emoji_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            ok = repo.delete_premium_emoji(emoji_id)
        return {"ok": ok}

    frontend_dist = Path("frontend/dist")
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{path:path}")
        async def spa():
            return FileResponse(frontend_dist / "index.html")
    else:
        @app.get("/")
        async def no_frontend():
            return {
                "status": "frontend_not_built",
                "message": "Run `cd frontend && npm install && npm run build`.",
            }

    return app


app = create_web_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("app.web:app", host=settings.web_host, port=settings.web_port, reload=False)


if __name__ == "__main__":
    main()
