"""Croma (India) Retailer Adapter."""

from app.providers.base import ExtractedProduct
from app.providers.extractor import extractor
from app.providers.retailers.base import RetailerAdapter


class CromaAdapter(RetailerAdapter):
    """Adapter for Croma India (croma.com) - Electronics and mobile retail."""

    @property
    def name(self) -> str:
        return "Croma"

    @property
    def domain(self) -> str:
        return "croma.com"

    @property
    def country(self) -> str:
        return "IN"

    @property
    def currency(self) -> str:
        return "INR"

    def extract(self, html: str, url: str) -> ExtractedProduct | None:
        product = extractor.extract(html, base_url=url)
        if product and product.primary_offer:
            # Guarantee INR currency for Croma
            product.primary_offer.currency = "INR"
        return product
