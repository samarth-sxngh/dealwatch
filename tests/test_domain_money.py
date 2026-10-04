"""Unit tests for domain Money and currency binding."""

from decimal import Decimal

import pytest

from app.domain.money import CurrencyMismatchError, Money


def test_money_instantiation_and_quantization():
    m1 = Money("29999.00", "INR")
    assert m1.amount == Decimal("29999.00")
    assert m1.currency == "INR"

    # From int
    m2 = Money(30000, "inr")
    assert m2.amount == Decimal("30000.00")
    assert m2.currency == "INR"

    # Rounding
    m3 = Money(19.994, "USD")
    assert m3.amount == Decimal("19.99")
    m4 = Money(19.996, "USD")
    assert m4.amount == Decimal("20.00")


def test_invalid_money_currency():
    with pytest.raises(ValueError, match="Invalid ISO currency code"):
        Money("100", "INVALID")

    with pytest.raises(ValueError, match="Invalid monetary amount"):
        Money("not-a-number", "USD")


def test_money_string_formatting():
    assert str(Money(29999, "INR")) == "₹29,999.00"
    assert str(Money("199.99", "USD")) == "$199.99"
    assert str(Money("45.50", "GBP")) == "£45.50"
    assert str(Money("99.00", "EUR")) == "€99.00"
    assert str(Money("120.00", "CAD")) == "CA$120.00"


def test_money_comparisons():
    m1 = Money("29999.00", "INR")
    m2 = Money("30000.00", "INR")
    m3 = Money("29999.00", "INR")

    assert m1 < m2
    assert m1 <= m2
    assert m1 <= m3
    assert m1 == m3
    assert m2 > m1
    assert m2 >= m1


def test_currency_mismatch_raises():
    m_inr = Money("29999.00", "INR")
    m_usd = Money("29999.00", "USD")
    m_eur = Money("29999.00", "EUR")

    with pytest.raises(CurrencyMismatchError):
        _ = m_inr < m_usd

    with pytest.raises(CurrencyMismatchError):
        _ = m_inr > m_eur

    with pytest.raises(CurrencyMismatchError):
        _ = m_usd + m_eur

    with pytest.raises(CurrencyMismatchError):
        _ = m_inr - m_usd


def test_money_arithmetic():
    m1 = Money("30000.00", "INR")
    m2 = Money("29499.00", "INR")

    diff = m1 - m2
    assert diff == Money("501.00", "INR")
    assert m1.difference_amount(m2) == Decimal("501.00")
    assert m2.difference_amount(m1) == Decimal("501.00")

    sum_m = m1 + Money("500.00", "INR")
    assert sum_m == Money("30500.00", "INR")
