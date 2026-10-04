"""B&H Photo Video (US) Retailer Adapter."""

from app.providers.base import ExtractedProduct
from app.providers.extractor import extractor
from app.providers.retailers.base import RetailerAdapter


class BhPhotoAdapter(RetailerAdapter):
    """Adapter for B&H Photo Video (bhphotovideo.com) - Electronics and cameras."""

    @property
    def name(self) -> str:
        return "B&H Photo"

    @property
    def domain(self) -> str:
        return "bhphotovideo.com"

    @property
    def country(self) -> str:
        return "US"

    @property
    def currency(self) -> str:
        return "USD"

    def extract(self, html: str, url: str) -> ExtractedProduct | None:
        product = extractor.extract(html, base_url=url)
        if product and product.primary_offer:
            product.primary_offer.currency = "USD"
        return product
