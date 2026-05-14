from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Draft, PremiumEmoji, Product, ScheduledPost, Setting
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
        if not product.order_url:
            product.order_url = data.url
        product.visibility = data.visibility
        product.is_active = data.is_active
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
            url=product.order_url or product.url,
            visibility=product.visibility,
            is_active=product.is_active,
        )

    def get_next_unpublished(self) -> Product | None:
        return self.session.scalar(
            select(Product)
            .where(Product.is_published.is_(False), Product.is_excluded.is_(False), Product.is_active.is_(True))
            .order_by(Product.created_at.asc())
        )

    def list_products(self, status: str = "new", limit: int = 10, offset: int = 0) -> list[Product]:
        stmt = select(Product).order_by(Product.created_at.desc()).limit(limit).offset(offset)
        if status == "new":
            stmt = stmt.where(Product.is_published.is_(False), Product.is_excluded.is_(False), Product.is_active.is_(True))
        elif status == "active":
            stmt = stmt.where(Product.is_active.is_(True))
        elif status == "archive":
            stmt = stmt.where(Product.is_active.is_(False))
        elif status == "published":
            stmt = stmt.where(Product.is_published.is_(True))
        elif status == "excluded":
            stmt = stmt.where(Product.is_excluded.is_(True))
        elif status == "all":
            pass
        else:
            stmt = stmt.where(Product.is_published.is_(False), Product.is_excluded.is_(False), Product.is_active.is_(True))
        return list(self.session.scalars(stmt))

    def count_products(self, status: str = "new") -> int:
        stmt = select(func.count()).select_from(Product)
        if status == "new":
            stmt = stmt.where(Product.is_published.is_(False), Product.is_excluded.is_(False), Product.is_active.is_(True))
        elif status == "active":
            stmt = stmt.where(Product.is_active.is_(True))
        elif status == "archive":
            stmt = stmt.where(Product.is_active.is_(False))
        elif status == "published":
            stmt = stmt.where(Product.is_published.is_(True))
        elif status == "excluded":
            stmt = stmt.where(Product.is_excluded.is_(True))
        return int(self.session.scalar(stmt) or 0)

    def search_products(self, query: str = "", status: str = "active", limit: int = 50, offset: int = 0) -> tuple[list[Product], int]:
        stmt = select(Product).order_by(Product.updated_at.desc())
        count_stmt = select(func.count()).select_from(Product)
        filters = []
        if status == "active":
            filters.append(Product.is_active.is_(True))
        elif status == "archive":
            filters.append(Product.is_active.is_(False))
        elif status == "new":
            filters.extend([Product.is_active.is_(True), Product.is_published.is_(False), Product.is_excluded.is_(False)])
        elif status == "published":
            filters.append(Product.is_published.is_(True))
        elif status == "excluded":
            filters.append(Product.is_excluded.is_(True))
        if query:
            like = f"%{query}%"
            filters.append(
                Product.name.ilike(like)
                | Product.offer_id.ilike(like)
                | Product.product_id.ilike(like)
                | Product.sku.ilike(like)
                | Product.brand.ilike(like)
            )
        for item in filters:
            stmt = stmt.where(item)
            count_stmt = count_stmt.where(item)
        total = int(self.session.scalar(count_stmt) or 0)
        products = list(self.session.scalars(stmt.limit(limit).offset(offset)))
        return products, total

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

    def update_draft_text(self, draft: Draft, text: str) -> None:
        draft.text = text
        self.session.commit()

    def update_draft_status(self, draft: Draft, status: str) -> None:
        draft.status = status
        self.session.commit()

    def exclude_product(self, product: Product, value: bool = True) -> None:
        product.is_excluded = value
        self.session.commit()

    def set_product_active(self, product: Product, value: bool) -> None:
        product.is_active = value
        self.session.commit()

    def update_product_admin_fields(self, product: Product, order_url: str | None, is_active: bool, is_excluded: bool) -> None:
        product.order_url = order_url
        product.is_active = is_active
        product.is_excluded = is_excluded
        self.session.commit()

    def dashboard_counts(self) -> dict[str, int]:
        return {
            "all": int(self.session.scalar(select(func.count()).select_from(Product)) or 0),
            "active": self.count_products("active"),
            "archive": self.count_products("archive"),
            "new": self.count_products("new"),
            "published": self.count_products("published"),
            "drafts": self.count_drafts("pending"),
        }

    def list_premium_emojis(self, include_inactive: bool = True) -> list[PremiumEmoji]:
        stmt = select(PremiumEmoji).order_by(PremiumEmoji.label.asc())
        if not include_inactive:
            stmt = stmt.where(PremiumEmoji.is_active.is_(True))
        return list(self.session.scalars(stmt))

    def create_premium_emoji(
        self,
        label: str,
        emoji: str,
        telegram_custom_emoji_id: str | None,
        description: str | None,
    ) -> PremiumEmoji:
        item = PremiumEmoji(
            label=label,
            emoji=emoji,
            telegram_custom_emoji_id=telegram_custom_emoji_id,
            description=description,
        )
        self.session.add(item)
        self.session.commit()
        return item

    def delete_premium_emoji(self, emoji_id: int) -> bool:
        item = self.session.get(PremiumEmoji, emoji_id)
        if item is None:
            return False
        self.session.delete(item)
        self.session.commit()
        return True

    def list_scheduled_posts(self, status: str = "scheduled", limit: int = 100, offset: int = 0) -> list[ScheduledPost]:
        stmt = select(ScheduledPost).order_by(ScheduledPost.scheduled_at.asc()).limit(limit).offset(offset)
        if status != "all":
            stmt = stmt.where(ScheduledPost.status == status)
        return list(self.session.scalars(stmt))

    def create_scheduled_post(self, draft_id: int, scheduled_at: datetime) -> ScheduledPost:
        item = ScheduledPost(draft_id=draft_id, scheduled_at=scheduled_at)
        self.session.add(item)
        self.session.commit()
        return item

    def delete_scheduled_post(self, scheduled_id: int) -> bool:
        item = self.session.get(ScheduledPost, scheduled_id)
        if item is None:
            return False
        self.session.delete(item)
        self.session.commit()
        return True

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

    def get_settings_map(self) -> dict[str, str]:
        return {item.key: item.value for item in self.session.scalars(select(Setting))}
