from pydantic import BaseModel, Field


class ProductData(BaseModel):
    offer_id: str
    product_id: str | None = None
    sku: str | None = None
    name: str
    brand: str | None = None
    category: str | None = None
    description: str | None = None
    attributes: list[dict] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    price: str | None = None
    page_price: str | None = None
    stock: int | None = None
    url: str | None = None
    visibility: str | None = None
    is_active: bool = True
