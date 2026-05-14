from __future__ import annotations

import secrets
from pathlib import Path

import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm import OllamaGenerator
from app.logging_config import setup_logging
from app.models import Draft, PremiumEmoji, Product, make_session_factory
from app.ozon_client import OzonClient
from app.repository import Repository
from app.service import PostService

security = HTTPBasic()


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


def require_admin(
    credentials: HTTPBasicCredentials = Depends(security),
    settings: Settings = Depends(get_settings),
) -> str:
    valid_username = secrets.compare_digest(credentials.username, settings.web_admin_username)
    valid_password = secrets.compare_digest(credentials.password, settings.web_admin_password)
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


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

    @app.get("/api/me")
    async def me(_: str = Depends(require_admin)):
        return {"name": "Аромат дня", "channel": settings.telegram_channel_id}

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

    @app.post("/api/drafts/{draft_id}/reject")
    async def reject_draft(draft_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            draft = repo.get_draft(draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft not found")
            repo.reject_draft(draft)
            return draft_payload(draft)

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
        async def spa(_: str = Depends(require_admin)):
            return FileResponse(frontend_dist / "index.html")
    else:
        @app.get("/")
        async def no_frontend(_: str = Depends(require_admin)):
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
