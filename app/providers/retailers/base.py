"""Abstract base class for retailer adapters."""

from abc import ABC, abstractmethod
from urllib.parse import urlparse

from app.providers.base import ExtractedProduct


class RetailerAdapter(ABC):
    """Base interface for domain-specific retailer extraction adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Friendly retailer name, e.g. 'Croma'."""

    @property
    @abstractmethod
    def domain(self) -> str:
        """Root domain, e.g. 'croma.com'."""

    @property
    @abstractmethod
    def country(self) -> str:
        """ISO 3166-1 alpha-2 country code, e.g. 'IN'."""

    @property
    @abstractmethod
    def currency(self) -> str:
        """ISO 4217 currency code, e.g. 'INR'."""

    @property
    def access_tier(self) -> int:
        """Access tier (1: API, 2: Permitted Structured Pages, 3: User Data, 4: Deep Link)."""
        return 2

    def can_handle(self, url: str) -> bool:
        """Checks if this adapter is designated to handle the given URL."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        host = host.removeprefix("www.")
        return host == self.domain or host.endswith(f".{self.domain}")

    @abstractmethod
    def extract(self, html: str, url: str) -> ExtractedProduct | None:
        """Extracts structured product and pricing information from the page HTML."""
