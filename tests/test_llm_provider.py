"""Unit and integration tests for Groq LLM provider, schemas, caching, and rate caps."""

from decimal import Decimal

import pytest

from app.config import settings
from app.providers.llm import (
    GroqLLMProvider,
    LLMExtractedProduct,
    LLMMatchVerification,
)


def test_llm_extracted_product_schema_validation():
    data = {
        "title": "Apple iPhone 15 128GB Blue",
        "brand": "Apple",
        "model": "iPhone 15",
        "variant": "128GB Blue",
        "gtin": "0194253782910",
        "mpn": "MTP43HN/A",
        "price": "79900.00",
        "currency": "INR",
        "availability": "in_stock",
        "condition": "new",
    }
    extracted = LLMExtractedProduct.model_validate(data)
    assert extracted.title == "Apple iPhone 15 128GB Blue"
    assert extracted.brand == "Apple"
    assert extracted.price == Decimal("79900.00")
    assert extracted.currency == "INR"
    assert extracted.availability == "in_stock"


def test_llm_match_verification_schema():
    data = {
        "is_exact_match": True,
        "confidence": "exact",
        "matched_on": "llm_verified",
        "reasons": ["Brand, model, and storage 128GB match precisely."],
    }
    verification = LLMMatchVerification.model_validate(data)
    assert verification.is_exact_match is True
    assert verification.confidence == "exact"
    assert len(verification.reasons) == 1


@pytest.mark.asyncio
async def test_llm_provider_daily_cap_enforcement():
    provider = GroqLLMProvider(api_key="gsk-test", model="openai/gpt-oss-20b", max_daily_calls=2)
    assert provider.has_quota() is True
    assert provider.remaining_calls_today == 2

    # Simulate 2 calls
    provider._calls_today = 2
    assert provider.has_quota() is False
    assert provider.remaining_calls_today == 0

    # Call should be refused gracefully without calling network
    res = await provider.extract_product_from_text("some text")
    assert res is None

    match_res = await provider.verify_borderline_match({"title": "A"}, {"title": "B"})
    assert match_res.status == "uncertain"
    assert "quota" in match_res.reasons[0].lower() or "unable" in match_res.reasons[0].lower()


@pytest.mark.asyncio
async def test_llm_provider_caching():
    provider = GroqLLMProvider(api_key="gsk-test", model="openai/gpt-oss-20b", max_daily_calls=50)

    # Pre-populate cache
    cache_key = provider._make_cache_key("test_system\ntest_user")
    mock_val = LLMExtractedProduct(title="Cached Product", brand="TestBrand")
    provider._cache[cache_key] = mock_val

    # Call api with retry - should return from cache directly
    val = await provider._call_api_with_retry("test_system", "test_user", LLMExtractedProduct)
    assert val == mock_val
    assert provider.calls_today == 0  # No API call made


@pytest.mark.asyncio
async def test_live_groq_extraction_and_matching():
    """Live integration test against Groq using user's configured GROQ_API_KEY and GROQ_MODEL."""
    if not settings.GROQ_API_KEY:
        pytest.skip("GROQ_API_KEY not set in environment.")

    provider = GroqLLMProvider()

    # 1. Fallback text extraction
    messy_text = (
        "Special Festive Offer! Buy the brand new Samsung Galaxy S24 Ultra 5G (Titanium Gray, 256 GB) "
        "at an unbelievable deal of Rs. 129999. In stock with standard manufacturer warranty. "
        "Model code SM-S928B. Free delivery."
    )
    product = await provider.extract_product_from_text(messy_text, page_title="Samsung Deal")
    assert product is not None
    assert product.brand is not None and "samsung" in product.brand.lower()
    assert product.price is not None and product.price >= Decimal(100000)

    # 2. Borderline match verification - Exact match
    subject = {
        "title": "Samsung Galaxy S24 Ultra (256 GB, Titanium Gray)",
        "brand": "Samsung",
        "model": "Galaxy S24 Ultra",
        "variant": "256GB Gray",
    }
    candidate_exact = {
        "title": "Samsung Galaxy S24 Ultra 5G 256GB Titanium Gray Smartphone",
        "brand": "Samsung",
        "model": "Galaxy S24 Ultra",
        "variant": "256GB Titanium Gray",
    }
    match_exact = await provider.verify_borderline_match(subject, candidate_exact)
    assert match_exact.status in ("exact", "uncertain")  # Valid confidence

    # 3. Borderline match verification - Mismatch (different storage)
    candidate_mismatch = {
        "title": "Samsung Galaxy S24 Ultra 5G 512GB Titanium Black",
        "brand": "Samsung",
        "model": "Galaxy S24 Ultra",
        "variant": "512GB Black",
    }
    match_mismatch = await provider.verify_borderline_match(subject, candidate_mismatch)
    assert match_mismatch.status == "mismatch"
