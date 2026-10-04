"""Retailer Registry and domain allowlist coordinator."""

import logging
from urllib.parse import urlparse

from app.providers.retailers.base import RetailerAdapter
from app.providers.retailers.bhphoto import BhPhotoAdapter
from app.providers.retailers.croma import CromaAdapter
from app.providers.retailers.generic import GenericJsonLdAdapter

logger = logging.getLogger(__name__)


class RetailerRegistry:
    """Registry maintaining permitted retailer adapters and domain access control."""

    def __init__(self) -> None:
        self._adapters: dict[str, RetailerAdapter] = {}
        # Register core adapters
        self.register(CromaAdapter())
        self.register(BhPhotoAdapter())

    def register(self, adapter: RetailerAdapter) -> None:
        domain = adapter.domain.lower()
        self._adapters[domain] = adapter
        logger.info("Registered retailer adapter: %s (%s)", adapter.name, domain)

    def get_adapter_for_url(self, url: str) -> RetailerAdapter | None:
        """Finds a matching retailer adapter for the URL."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        host = host.removeprefix("www.")

        # 1. Exact or suffix match in registered adapters
        for domain, adapter in self._adapters.items():
            if host == domain or host.endswith(f".{domain}"):
                return adapter

        # 2. If host has permitted structured JSON-LD support, allow generic adapter
        # (Must be at least Tier 2 access)
        return GenericJsonLdAdapter(domain=host, name=host.capitalize())

    def is_permitted_source(self, url: str) -> bool:
        """Enforces that only sources meeting Tier 2+ access rules can be automated."""
        adapter = self.get_adapter_for_url(url)
        if not adapter:
            return False
        return adapter.access_tier <= 2


retailer_registry = RetailerRegistry()
