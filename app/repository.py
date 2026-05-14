from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Draft, Product, Setting
from app.schemas import ProductData


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_product(self, data: ProductData) -> Product:
        product = self.session.scalar(select(Product).where(Product.offer_id == data.offer_id))
        if product is None:
            product = Product(offer_id=data.offer_id, name=data.name)
            self.session.add(product)
        product.product_id = data.product_id
        product.sku = data.sku
        product.name = data.name
        product.brand = data.brand
        product.category = data.category
        product.description = data.description
        product.attributes_json = json.dumps(data.attributes, ensure_ascii=False)
        product.images_json = json.dumps(data.images, ensure_ascii=False)
        product.price = data.price
        product.stock = data.stock
        product.url = data.url
        self.session.commit()
        return product

    def product_to_data(self, product: Product) -> ProductData:
        return ProductData(
            offer_id=product.offer_id,
            product_id=product.product_id,
            sku=product.sku,
            name=product.name,
            brand=product.brand,
            category=product.category,
            description=product.description,
            attributes=json.loads(product.attributes_json or "[]"),
            images=json.loads(product.images_json or "[]"),
            price=product.price,
            stock=product.stock,
            url=product.url,
        )

    def get_next_unpublished(self) -> Product | None:
        return self.session.scalar(
            select(Product)
            .where(Product.is_published.is_(False), Product.is_excluded.is_(False))
            .order_by(Product.created_at.asc())
        )

    def list_products(self, status: str = "new", limit: int = 10, offset: int = 0) -> list[Product]:
        stmt = select(Product).order_by(Product.created_at.desc()).limit(limit).offset(offset)
        if status == "new":
            stmt = stmt.where(Product.is_published.is_(False), Product.is_excluded.is_(False))
        elif status == "published":
            stmt = stmt.where(Product.is_published.is_(True))
        elif status == "excluded":
            stmt = stmt.where(Product.is_excluded.is_(True))
        elif status == "all":
            pass
        else:
            stmt = stmt.where(Product.is_published.is_(False), Product.is_excluded.is_(False))
        return list(self.session.scalars(stmt))

    def count_products(self, status: str = "new") -> int:
        stmt = select(func.count()).select_from(Product)
        if status == "new":
            stmt = stmt.where(Product.is_published.is_(False), Product.is_excluded.is_(False))
        elif status == "published":
            stmt = stmt.where(Product.is_published.is_(True))
        elif status == "excluded":
            stmt = stmt.where(Product.is_excluded.is_(True))
        return int(self.session.scalar(stmt) or 0)

    def get_product(self, product_id: int) -> Product | None:
        return self.session.get(Product, product_id)

    def get_draft(self, draft_id: int) -> Draft | None:
        return self.session.get(Draft, draft_id)

    def list_drafts(self, status: str = "pending", limit: int = 10, offset: int = 0) -> list[Draft]:
        stmt = select(Draft).order_by(Draft.created_at.desc()).limit(limit).offset(offset)
        if status != "all":
            stmt = stmt.where(Draft.status == status)
        return list(self.session.scalars(stmt))

    def count_drafts(self, status: str = "pending") -> int:
        stmt = select(func.count()).select_from(Draft)
        if status != "all":
            stmt = stmt.where(Draft.status == status)
        return int(self.session.scalar(stmt) or 0)

    def latest_pending_draft(self, product_id: int) -> Draft | None:
        return self.session.scalar(
            select(Draft)
            .where(Draft.product_id == product_id, Draft.status == "pending")
            .order_by(Draft.created_at.desc())
        )

    def create_draft(self, product_id: int, text: str, style: str) -> Draft:
        draft = Draft(product_id=product_id, text=text, style=style)
        self.session.add(draft)
        self.session.commit()
        return draft

    def mark_published(self, product: Product, draft: Draft) -> None:
        product.is_published = True
        draft.status = "published"
        self.session.commit()

    def reject_draft(self, draft: Draft) -> None:
        draft.status = "rejected"
        self.session.commit()

    def exclude_product(self, product: Product, value: bool = True) -> None:
        product.is_excluded = value
        self.session.commit()

    def set_setting(self, key: str, value: str) -> None:
        setting = self.session.get(Setting, key)
        if setting is None:
            setting = Setting(key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
        self.session.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        setting = self.session.get(Setting, key)
        return setting.value if setting else default
