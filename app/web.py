from __future__ import annotations

import secrets

import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.llm import OllamaGenerator
from app.logging_config import setup_logging
from app.models import make_session_factory
from app.ozon_client import OzonClient
from app.repository import Repository
from app.service import PostService

security = HTTPBasic()
templates = Jinja2Templates(directory="app/templates")


def build_context(request: Request, settings: Settings) -> dict:
    return {
        "request": request,
        "settings": settings,
        "brand_name": "Аромат дня",
    }


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
    app = FastAPI(title="Аромат дня Admin")

    @app.get("/")
    async def dashboard(request: Request, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            counts = repo.dashboard_counts()
            products, _total = repo.search_products(status="new", limit=8)
            drafts = repo.list_drafts("pending", limit=8)
        return templates.TemplateResponse(
            "dashboard.html",
            build_context(request, settings) | {"counts": counts, "products": products, "drafts": drafts},
        )

    @app.get("/products")
    async def products(
        request: Request,
        q: str = "",
        status_filter: str = "active",
        page: int = 1,
        _: str = Depends(require_admin),
    ):
        page = max(1, page)
        limit = 40
        offset = (page - 1) * limit
        with session_factory() as session:
            repo = Repository(session)
            items, total = repo.search_products(q, status_filter, limit, offset)
        return templates.TemplateResponse(
            "products.html",
            build_context(request, settings)
            | {
                "products": items,
                "total": total,
                "q": q,
                "status_filter": status_filter,
                "page": page,
                "limit": limit,
            },
        )

    @app.get("/products/{product_id}")
    async def product_detail(request: Request, product_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            attrs = repo.product_to_data(product).attributes
            drafts = [draft for draft in repo.list_drafts("all", limit=30) if draft.product_id == product.id]
        return templates.TemplateResponse(
            "product_detail.html",
            build_context(request, settings) | {"product": product, "attrs": attrs, "drafts": drafts},
        )

    @app.post("/products/{product_id}")
    async def update_product(
        product_id: int,
        order_url: str = Form(""),
        is_active: str | None = Form(None),
        is_excluded: str | None = Form(None),
        _: str = Depends(require_admin),
    ):
        with session_factory() as session:
            repo = Repository(session)
            product = repo.get_product(product_id)
            if product is None:
                raise HTTPException(status_code=404, detail="Product not found")
            repo.update_product_admin_fields(
                product,
                order_url.strip() or None,
                is_active == "on",
                is_excluded == "on",
            )
        return RedirectResponse(f"/products/{product_id}", status_code=303)

    @app.post("/products/{product_id}/draft")
    async def create_draft(product_id: int, _: str = Depends(require_admin)):
        draft = await post_service.create_draft_for_product(product_id)
        if draft is None:
            raise HTTPException(status_code=400, detail="Draft was not created")
        return RedirectResponse(f"/products/{product_id}", status_code=303)

    @app.get("/drafts")
    async def drafts(request: Request, status_filter: str = "pending", page: int = 1, _: str = Depends(require_admin)):
        page = max(1, page)
        limit = 30
        offset = (page - 1) * limit
        with session_factory() as session:
            repo = Repository(session)
            items = repo.list_drafts(status_filter, limit, offset)
            total = repo.count_drafts(status_filter)
        return templates.TemplateResponse(
            "drafts.html",
            build_context(request, settings)
            | {"drafts": items, "total": total, "status_filter": status_filter, "page": page, "limit": limit},
        )

    @app.get("/emojis")
    async def emojis(request: Request, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            items = repo.list_premium_emojis()
        return templates.TemplateResponse("emojis.html", build_context(request, settings) | {"emojis": items})

    @app.post("/emojis")
    async def create_emoji(
        label: str = Form(...),
        emoji: str = Form(...),
        telegram_custom_emoji_id: str = Form(""),
        description: str = Form(""),
        _: str = Depends(require_admin),
    ):
        with session_factory() as session:
            repo = Repository(session)
            repo.create_premium_emoji(
                label.strip(),
                emoji.strip(),
                telegram_custom_emoji_id.strip() or None,
                description.strip() or None,
            )
        return RedirectResponse("/emojis", status_code=303)

    @app.post("/emojis/{emoji_id}/delete")
    async def delete_emoji(emoji_id: int, _: str = Depends(require_admin)):
        with session_factory() as session:
            repo = Repository(session)
            repo.delete_premium_emoji(emoji_id)
        return RedirectResponse("/emojis", status_code=303)

    return app


app = create_web_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("app.web:app", host=settings.web_host, port=settings.web_port, reload=False)


if __name__ == "__main__":
    main()
