"""Unit tests for price drop alerts, target price thresholds, and competitor comparison rules."""

import uuid
from decimal import Decimal

from app.domain.money import Money
from app.domain.rules import (
    evaluate_competitor_comparison,
    evaluate_price_drop,
    evaluate_target_price,
    make_competitor_cheaper_dedup_key,
    make_price_drop_dedup_key,
    make_target_reached_dedup_key,
    make_tracking_expired_dedup_key,
)


def test_price_drop_alerts_exact_scenarios():
    # 1. 30000 -> 29999 alerts (even 1 unit drop)
    prev = Money(30000, "INR")
    curr_drop = Money(29999, "INR")
    res1 = evaluate_price_drop(prev, curr_drop, is_available=True)
    assert res1.is_alertable is True
    assert res1.drop_amount == Money(1, "INR")

    # 2. 30000 -> 30000 does NOT alert
    curr_same = Money(30000, "INR")
    res2 = evaluate_price_drop(prev, curr_same, is_available=True)
    assert res2.is_alertable is False

    # 3. 30000 -> 30100 does NOT alert (price rise)
    curr_rise = Money(30100, "INR")
    res3 = evaluate_price_drop(prev, curr_rise, is_available=True)
    assert res3.is_alertable is False


def test_price_drop_availability_and_failure_guards():
    prev = Money(30000, "INR")
    curr = Money(25000, "INR")

    # Out of stock drop does NOT alert
    res_oos = evaluate_price_drop(prev, curr, is_available=False)
    assert res_oos.is_alertable is False

    # Failed check does NOT alert
    res_failed = evaluate_price_drop(prev, curr, is_available=True, price_status="failed")
    assert res_failed.is_alertable is False

    # Currency mismatch does NOT alert
    curr_usd = Money(25000, "USD")
    res_mismatch = evaluate_price_drop(prev, curr_usd, is_available=True)
    assert res_mismatch.is_alertable is False


def test_target_price_threshold_scenarios():
    target = Money(30000, "INR")

    # Target 30000, Current 29999 -> alerts
    res1 = evaluate_target_price(target, Money(29999, "INR"), is_available=True)
    assert res1.is_alertable is True

    # Target 30000, Current 30000 -> alerts (current <= target)
    res2 = evaluate_target_price(target, Money(30000, "INR"), is_available=True)
    assert res2.is_alertable is True

    # Target 29999, Current 30000 -> does NOT alert
    target_lower = Money(29999, "INR")
    res3 = evaluate_target_price(target_lower, Money(30000, "INR"), is_available=True)
    assert res3.is_alertable is False

    # Currency mismatch refuses comparison
    res_curr_mismatch = evaluate_target_price(target, Money(25000, "USD"), is_available=True)
    assert res_curr_mismatch.is_alertable is False


def test_competitor_cheaper_evaluation():
    orig_price = Money("29499.00", "INR")
    comp_price = Money("28999.00", "INR")

    # Exact verified match in stock -> alerts
    res1 = evaluate_competitor_comparison(
        original_source_name="Amazon India",
        original_price=orig_price,
        original_has_full_total=True,
        competitor_source_name="Flipkart",
        competitor_price=comp_price,
        competitor_has_full_total=True,
        competitor_match_status="exact",
        competitor_is_available=True,
    )
    assert res1.is_alertable is True
    assert res1.savings == Money("500.00", "INR")
    assert "Flipkart ₹28,999.00 is cheaper than Amazon India" in res1.message

    # Competitor is uncertain -> does NOT alert
    res2 = evaluate_competitor_comparison(
        original_source_name="Amazon India",
        original_price=orig_price,
        original_has_full_total=True,
        competitor_source_name="Flipkart",
        competitor_price=comp_price,
        competitor_has_full_total=True,
        competitor_match_status="uncertain",
        competitor_is_available=True,
    )
    assert res2.is_alertable is False

    # Competitor is out of stock -> does NOT alert
    res3 = evaluate_competitor_comparison(
        original_source_name="Amazon India",
        original_price=orig_price,
        original_has_full_total=True,
        competitor_source_name="Flipkart",
        competitor_price=comp_price,
        competitor_has_full_total=True,
        competitor_match_status="exact",
        competitor_is_available=False,
    )
    assert res3.is_alertable is False


def test_deduplication_key_generation():
    tid = uuid.uuid4()
    oid = uuid.uuid4()

    key_drop = make_price_drop_dedup_key(tid, oid, Decimal("28999.00"), "INR", "2026-10-02")
    assert key_drop == f"tracker:{tid}:offer:{oid}:price_drop:28999.00:INR:2026-10-02"

    key_target = make_target_reached_dedup_key(tid, Decimal("29000.00"), "INR")
    assert key_target == f"tracker:{tid}:target_reached:29000.00:INR"

    key_comp = make_competitor_cheaper_dedup_key(tid, oid, Decimal("28499.00"), "INR", "2026-10-02")
    assert key_comp == f"tracker:{tid}:competitor:{oid}:cheaper:28499.00:INR:2026-10-02"

    key_expired = make_tracking_expired_dedup_key(tid)
    assert key_expired == f"tracker:{tid}:tracking_expired"
