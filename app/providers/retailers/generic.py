"""Generic Schema.org JSON-LD Retailer Adapter."""

from app.domain.market import detect_market_from_domain
from app.providers.base import ExtractedProduct
from app.providers.extractor import extractor
from app.providers.retailers.base import RetailerAdapter


class GenericJsonLdAdapter(RetailerAdapter):
    """Adapter for permitted structured websites exposing Schema.org Product data."""

    def __init__(self, domain: str, name: str, country: str = "US", currency: str = "USD") -> None:
        self._domain = domain
        self._name = name
        self._country = country
        self._currency = currency

    @property
    def name(self) -> str:
        return self._name

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def country(self) -> str:
        return self._country

    @property
    def currency(self) -> str:
        return self._currency

    def extract(self, html: str, url: str) -> ExtractedProduct | None:
        product = extractor.extract(html, base_url=url)
        if product and product.primary_offer and not product.primary_offer.currency:
            market = detect_market_from_domain(url)
            product.primary_offer.currency = market.currency or self._currency
        return product
