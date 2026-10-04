"""Providers package for fetching, extraction, retailer adapters, and LLM fallback."""

from app.providers.base import ExtractedOffer, ExtractedProduct, FetchResult
from app.providers.extractor import StructuredExtractor, extractor
from app.providers.fetcher import SafeFetcher, SSRFValidationError, fetcher
from app.providers.firecrawl import FirecrawlClient, firecrawl_client
from app.providers.llm import (
    GroqLLMProvider,
    LLMExtractedProduct,
    LLMMatchVerification,
    llm_provider,
)
from app.providers.retailers.base import RetailerAdapter
from app.providers.retailers.registry import RetailerRegistry, retailer_registry

__all__ = [
    "ExtractedOffer",
    "ExtractedProduct",
    "FetchResult",
    "FirecrawlClient",
    "GroqLLMProvider",
    "LLMExtractedProduct",
    "LLMMatchVerification",
    "RetailerAdapter",
    "RetailerRegistry",
    "SSRFValidationError",
    "SafeFetcher",
    "StructuredExtractor",
    "extractor",
    "fetcher",
    "firecrawl_client",
    "llm_provider",
    "retailer_registry",
]
