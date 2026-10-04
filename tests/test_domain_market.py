"""Unit tests for domain-driven market and currency resolution."""

from app.domain.market import (
    MarketInfo,
    detect_market_from_domain,
    reconcile_market,
)


def test_known_domain_market_detection():
    # India
    m_in = detect_market_from_domain("https://www.amazon.in/dp/B0CHX1W1XY")
    assert m_in.country == "IN"
    assert m_in.currency == "INR"
    assert m_in.confidence == "high"

    m_fk = detect_market_from_domain("flipkart.com")
    assert m_fk.country == "IN"
    assert m_fk.currency == "INR"
    assert m_fk.confidence == "high"

    # United States
    m_us = detect_market_from_domain("bestbuy.com")
    assert m_us.country == "US"
    assert m_us.currency == "USD"

    # United Kingdom
    m_uk = detect_market_from_domain("amazon.co.uk")
    assert m_uk.country == "GB"
    assert m_uk.currency == "GBP"

    # Germany / EU
    m_de = detect_market_from_domain("amazon.de")
    assert m_de.country == "DE"
    assert m_de.currency == "EUR"

    # Canada
    m_ca = detect_market_from_domain("amazon.ca")
    assert m_ca.country == "CA"
    assert m_ca.currency == "CAD"


def test_generic_and_unknown_domains():
    # Generic .com
    m_com = detect_market_from_domain("somegenericstore.com")
    assert m_com.country == "US"
    assert m_com.currency == "USD"
    assert m_com.confidence == "medium"

    # Completely unknown TLD
    m_unknown = detect_market_from_domain("obscurestore.xyz")
    assert m_unknown.confidence == "needs_input"
    assert m_unknown.clarification_prompt == "Which country should I search in?"


def test_reconcile_market_with_page_currency():
    base = MarketInfo(country="IN", currency="INR", confidence="high")

    # Matching page currency keeps high confidence
    rec1 = reconcile_market(base, "INR")
    assert rec1.currency == "INR"
    assert rec1.confidence == "high"

    # Differing page currency takes precedence for pricing
    rec2 = reconcile_market(base, "USD")
    assert rec2.currency == "USD"
    assert rec2.confidence == "medium"
