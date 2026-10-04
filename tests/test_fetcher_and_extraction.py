"""Unit and fixture integration tests for SSRF-safe fetcher, extractor, adapters, and Firecrawl fallback."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.providers.extractor import extractor
from app.providers.fetcher import SSRFValidationError, fetcher
from app.providers.firecrawl import FirecrawlClient
from app.providers.retailers.registry import retailer_registry

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


def test_ssrf_validation_blocks_unsafe_targets():
    # Insecure schemes
    with pytest.raises(SSRFValidationError, match="Only HTTPS is permitted"):
        fetcher.validate_url_security("http://croma.com")

    # Localhost / loopback
    with pytest.raises(SSRFValidationError, match="Blocked access"):
        fetcher.validate_url_security("https://127.0.0.1/admin")

    with pytest.raises(SSRFValidationError, match="Blocked access"):
        fetcher.validate_url_security("https://localhost/admin")

    # Cloud metadata IP (AWS/GCP instance credentials theft vector)
    with pytest.raises(SSRFValidationError, match="Blocked access"):
        fetcher.validate_url_security("https://169.254.169.254/latest/meta-data")

    # Private internal IPs
    with pytest.raises(SSRFValidationError, match="Blocked access"):
        fetcher.validate_url_security("https://10.0.0.1/internal")

    with pytest.raises(SSRFValidationError, match="Blocked access"):
        fetcher.validate_url_security("https://192.168.1.1/router")

    with pytest.raises(SSRFValidationError, match="Blocked access"):
        fetcher.validate_url_security("https://172.16.0.5/api")


def test_ssrf_validation_allows_safe_public_urls():
    # Valid public HTTPS domain (should not raise)
    fetcher.validate_url_security("https://www.croma.com/p/300652")
    fetcher.validate_url_security("https://www.bhphotovideo.com/c/product/1668862-REG")


def test_extract_croma_fixture():
    html = read_fixture("croma_iphone.html")
    product = extractor.extract(html, base_url="https://www.croma.com")
    assert product is not None
    assert product.title == "Apple iPhone 15 (128GB, Blue)"
    assert product.brand == "Apple"
    assert product.model == "iPhone 15"
    assert product.gtin == "0194253782910"
    assert product.mpn == "MTP43HN/A"

    assert product.primary_offer is not None
    assert product.primary_offer.currency == "INR"
    assert product.primary_offer.total_price == Decimal("71990.00")
    assert product.primary_offer.availability == "in_stock"
    assert product.primary_offer.condition == "new"


def test_extract_bhphoto_fixture():
    html = read_fixture("bhphoto_camera.html")
    product = extractor.extract(html, base_url="https://www.bhphotovideo.com")
    assert product is not None
    assert product.title == "Sony Alpha a7 IV Mirrorless Camera"
    assert product.brand == "Sony"
    assert product.model == "a7 IV"
    assert product.mpn == "ILCE-7M4/B"
    assert product.gtin == "027242923980"

    assert product.primary_offer is not None
    assert product.primary_offer.currency == "USD"
    assert product.primary_offer.total_price == Decimal("2498.00")
    assert product.primary_offer.availability == "in_stock"


def test_extract_out_of_stock_fixture():
    html = read_fixture("out_of_stock.html")
    product = extractor.extract(html)
    assert product is not None
    assert product.primary_offer is not None
    assert product.primary_offer.availability == "out_of_stock"


def test_extract_refurbished_fixture():
    html = read_fixture("refurbished.html")
    product = extractor.extract(html)
    assert product is not None
    assert product.primary_offer is not None
    assert product.primary_offer.condition == "refurbished"


def test_extract_opengraph_fallback():
    html = read_fixture("opengraph_fallback.html")
    product = extractor.extract(html)
    assert product is not None
    assert product.title == "Bose QuietComfort 45 Headphones"
    assert product.primary_offer is not None
    assert product.primary_offer.total_price == Decimal("279.00")
    assert product.primary_offer.currency == "USD"


def test_retailer_registry_lookup_and_tier_rules():
    # Croma
    adapter_croma = retailer_registry.get_adapter_for_url("https://www.croma.com/p/300652")
    assert adapter_croma is not None
    assert adapter_croma.name == "Croma"
    assert adapter_croma.country == "IN"
    assert adapter_croma.currency == "INR"
    assert adapter_croma.access_tier == 2

    # B&H Photo
    adapter_bh = retailer_registry.get_adapter_for_url("https://bhphotovideo.com/c/product/123")
    assert adapter_bh is not None
    assert adapter_bh.name == "B&H Photo"
    assert adapter_bh.country == "US"

    # Generic
    adapter_gen = retailer_registry.get_adapter_for_url("https://example-shop.com/item")
    assert adapter_gen is not None
    assert adapter_gen.access_tier == 2

    # Permitted check
    assert retailer_registry.is_permitted_source("https://www.croma.com/p/123") is True


@pytest.mark.asyncio
async def test_firecrawl_credit_caps_and_refusal():
    # Test client without key
    client_no_key = FirecrawlClient(api_key="")
    res_no_key = await client_no_key.scrape("https://example.com")
    assert res_no_key.is_success is False
    assert "not configured" in res_no_key.error_message

    # Test client with simulated cap exhaustion
    client_exhausted = FirecrawlClient(api_key="fc-simulated-key")
    client_exhausted._credits_used = 100  # Equal to FIRECRAWL_MAX_CREDITS
    assert client_exhausted.has_available_credits() is False

    res_blocked = await client_exhausted.scrape("https://example.com")
    assert res_blocked.is_success is False
    assert res_blocked.status_code == 429
    assert "credit cap reached" in res_blocked.error_message
