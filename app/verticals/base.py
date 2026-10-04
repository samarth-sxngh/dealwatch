"""Base definitions and abstract plugin interface for multi-vertical comparison."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class SubjectDraft(BaseModel):
    """Normalized subject data parsed from a URL or text query."""

    vertical: str
    normalized_key: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    # Product specific fields (if vertical == 'products')
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


class OfferDraft(BaseModel):
    """Candidate or extracted offer details."""

    source_domain: str
    url_or_deeplink: str
    currency: str
    base_price: Decimal | None = None
    fees: Decimal | None = None
    taxes: Decimal | None = None
    discounts: Decimal | None = None
    total_price: Decimal | None = None
    availability: str = "unknown"  # in_stock, out_of_stock, preorder, unknown
    condition: str = "new"
    seller: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ObservationDraft(BaseModel):
    """Observation data extracted during a check run."""

    currency: str
    base_price: Decimal | None = None
    fees: Decimal | None = None
    taxes: Decimal | None = None
    total_price: Decimal | None = None
    availability: str = "unknown"
    price_status: str = "ok"  # ok, unavailable, failed
    raw_data: dict[str, Any] = Field(default_factory=dict)


class MatchResult(BaseModel):
    """Match status outcome."""

    status: Literal["exact", "uncertain", "mismatch"]
    matched_on: str | None = None  # gtin, mpn, sku, brand_model_variant, llm_verified
    reasons: list[str] = Field(default_factory=list)


class VerticalPlugin(ABC):
    """Abstract interface that every vertical (Products, Flights, etc.) must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Vertical identifier, e.g. 'products'."""

    @abstractmethod
    def parse_request(self, input_data: str | dict[str, Any]) -> SubjectDraft:
        """Parses a user input (URL or query) into a normalized SubjectDraft."""

    @abstractmethod
    def match(self, subject: Any, offer: Any) -> MatchResult:
        """Verifies if an offer is an exact match for the subject."""

    @abstractmethod
    def calculate_total_cost(self, offer: Any) -> Decimal | None:
        """Computes total cost according to vertical comparison rules."""

    @abstractmethod
    def is_alertable_price_drop(
        self,
        prev_currency: str,
        prev_price: Decimal | None,
        curr_currency: str,
        curr_price: Decimal | None,
        is_available: bool,
    ) -> bool:
        """Determines if a price change qualifies for a price drop alert."""

    @abstractmethod
    def is_alertable_target_reached(
        self,
        target_currency: str,
        target_price: Decimal,
        curr_currency: str,
        curr_price: Decimal | None,
        is_available: bool,
    ) -> bool:
        """Determines if the current price satisfies user's target threshold."""
