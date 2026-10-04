"""Base data transfer models and interfaces for providers."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class FetchResult:
    """Outcome of an HTTP fetch operation."""

    url: str
    status_code: int
    content: str
    content_type: str
    is_success: bool
    error_message: str | None = None
    used_fallback: bool = False


class ExtractedOffer(BaseModel):
    """Normalized offer details extracted from structured page data."""

    currency: str
    base_price: Decimal | None = None
    fees: Decimal | None = None
    taxes: Decimal | None = None
    total_price: Decimal | None = None
    availability: str = "unknown"  # in_stock, out_of_stock, preorder, unknown
    condition: str = "new"  # new, refurbished, used
    seller: str | None = None
    price_status: str = "ok"  # ok, unavailable, failed
    raw_data: dict[str, Any] = Field(default_factory=dict)


class ExtractedProduct(BaseModel):
    """Normalized product data extracted from a retailer page."""

    title: str
    brand: str | None = None
    model: str | None = None
    variant: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    sku: str | None = None
    description: str | None = None
    image_url: str | None = None
    raw_specs: dict[str, Any] = Field(default_factory=dict)
    primary_offer: ExtractedOffer | None = None
    all_offers: list[ExtractedOffer] = Field(default_factory=list)
