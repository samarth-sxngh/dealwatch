"""Products Vertical Plugin (Vertical #1)."""

from decimal import Decimal
from typing import Any

from app.domain.matching import match_product
from app.domain.money import Money
from app.domain.rules import evaluate_price_drop, evaluate_target_price
from app.verticals.base import (
    MatchResult,
    SubjectDraft,
    VerticalPlugin,
)
from app.verticals.registry import registry


class ProductsVertical(VerticalPlugin):
    """Vertical #1: Product shopping and retail deal discovery."""

    @property
    def name(self) -> str:
        return "products"

    def parse_request(self, input_data: str | dict[str, Any]) -> SubjectDraft:
        if isinstance(input_data, str):
            key = input_data.strip().lower()
            return SubjectDraft(
                vertical="products",
                normalized_key=key,
                title=input_data,
            )
        return SubjectDraft(
            vertical="products",
            normalized_key=input_data.get("normalized_key", "unknown"),
            title=input_data.get("title", "Unknown Product"),
            brand=input_data.get("brand"),
            model=input_data.get("model"),
            variant=input_data.get("variant"),
            gtin=input_data.get("gtin"),
            mpn=input_data.get("mpn"),
            sku=input_data.get("sku"),
            description=input_data.get("description"),
            image_url=input_data.get("image_url"),
            raw_specs=input_data.get("raw_specs", {}),
        )

    def match(self, subject: Any, offer: Any) -> MatchResult:
        """Invokes domain matching hierarchy."""
        # Convert ORM or dict objects to dict
        subj_dict = {
            "title": getattr(subject, "title", None)
            or (subject.get("title") if isinstance(subject, dict) else ""),
            "brand": getattr(subject, "brand", None)
            or (subject.get("brand") if isinstance(subject, dict) else None),
            "model": getattr(subject, "model", None)
            or (subject.get("model") if isinstance(subject, dict) else None),
            "variant": getattr(subject, "variant", None)
            or (subject.get("variant") if isinstance(subject, dict) else None),
            "gtin": getattr(subject, "gtin", None)
            or (subject.get("gtin") if isinstance(subject, dict) else None),
            "mpn": getattr(subject, "mpn", None)
            or (subject.get("mpn") if isinstance(subject, dict) else None),
            "condition": getattr(subject, "condition", "new")
            or (subject.get("condition", "new") if isinstance(subject, dict) else "new"),
            "raw_specs": getattr(subject, "raw_specs", {})
            or (subject.get("raw_specs", {}) if isinstance(subject, dict) else {}),
        }
        offer_dict = {
            "title": getattr(offer, "title", None)
            or (offer.get("title") if isinstance(offer, dict) else ""),
            "brand": getattr(offer, "brand", None)
            or (offer.get("brand") if isinstance(offer, dict) else None),
            "model": getattr(offer, "model", None)
            or (offer.get("model") if isinstance(offer, dict) else None),
            "variant": getattr(offer, "variant", None)
            or (offer.get("variant") if isinstance(offer, dict) else None),
            "gtin": getattr(offer, "gtin", None)
            or (offer.get("gtin") if isinstance(offer, dict) else None),
            "mpn": getattr(offer, "mpn", None)
            or (offer.get("mpn") if isinstance(offer, dict) else None),
            "condition": getattr(offer, "condition", "new")
            or (offer.get("condition", "new") if isinstance(offer, dict) else "new"),
            "attributes": getattr(offer, "attributes", {})
            or (offer.get("attributes", {}) if isinstance(offer, dict) else {}),
        }
        return match_product(subj_dict, offer_dict)

    def calculate_total_cost(self, offer: Any) -> Decimal | None:
        if hasattr(offer, "total_price") and offer.total_price is not None:
            return offer.total_price
        if hasattr(offer, "base_price") and offer.base_price is not None:
            return offer.base_price
        return None

    def is_alertable_price_drop(
        self,
        prev_currency: str,
        prev_price: Decimal | None,
        curr_currency: str,
        curr_price: Decimal | None,
        is_available: bool,
    ) -> bool:
        if prev_price is None or curr_price is None:
            return False
        if prev_currency != curr_currency:
            return False
        prev_m = Money(prev_price, prev_currency)
        curr_m = Money(curr_price, curr_currency)
        eval_res = evaluate_price_drop(prev_m, curr_m, is_available=is_available)
        return eval_res.is_alertable

    def is_alertable_target_reached(
        self,
        target_currency: str,
        target_price: Decimal,
        curr_currency: str,
        curr_price: Decimal | None,
        is_available: bool,
    ) -> bool:
        if curr_price is None:
            return False
        if target_currency != curr_currency:
            return False
        target_m = Money(target_price, target_currency)
        curr_m = Money(curr_price, curr_currency)
        eval_res = evaluate_target_price(target_m, curr_m, is_available=is_available)
        return eval_res.is_alertable


products_vertical = ProductsVertical()
registry.register(products_vertical)
