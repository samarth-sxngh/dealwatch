"""Unit tests for product matching hierarchy and negative match guards."""

from app.domain.matching import match_product, normalize_gtin


def test_gtin_normalization():
    assert normalize_gtin("0194253782910") == "0194253782910"
    assert normalize_gtin("194-253-782-910") == "194253782910"
    assert normalize_gtin("invalid") is None
    assert normalize_gtin("12345") is None  # Too short for GTIN-8/12/13/14


def test_gtin_exact_match():
    subject = {
        "title": "Apple iPhone 15 (128 GB) - Blue",
        "gtin": "0194253782910",
        "brand": "Apple",
        "condition": "new",
    }
    candidate = {
        "title": "Apple iPhone 15 128GB Blue 5G Smartphone",
        "gtin": "0194253782910",
        "brand": "Apple",
        "condition": "new",
    }
    res = match_product(subject, candidate)
    assert res.status == "exact"
    assert res.matched_on == "gtin"


def test_gtin_mismatch():
    subject = {
        "title": "Apple iPhone 15 (128 GB) - Blue",
        "gtin": "0194253782910",
        "brand": "Apple",
        "condition": "new",
    }
    candidate = {
        "title": "Apple iPhone 15 (256 GB) - Blue",
        "gtin": "0194253782927",
        "brand": "Apple",
        "condition": "new",
    }
    res = match_product(subject, candidate)
    assert res.status == "mismatch"


def test_mpn_and_brand_exact_match():
    subject = {
        "title": "Sony WH-1000XM5 Wireless Headphones - Black",
        "brand": "Sony",
        "mpn": "WH1000XM5/B",
        "condition": "new",
    }
    candidate = {
        "title": "Sony Noise Canceling Headphones WH-1000XM5 Black",
        "brand": "Sony",
        "mpn": "WH1000XM5/B",
        "condition": "new",
    }
    res = match_product(subject, candidate)
    assert res.status == "exact"
    assert res.matched_on == "mpn"


def test_condition_mismatch_refurbished_vs_new():
    subject = {
        "title": "Apple iPhone 15 128GB",
        "brand": "Apple",
        "condition": "new",
        "gtin": "0194253782910",
    }
    candidate = {
        "title": "Apple iPhone 15 128GB Refurbished Excellent Condition",
        "brand": "Apple",
        "condition": "refurbished",
        "gtin": "0194253782910",
    }
    res = match_product(subject, candidate)
    assert res.status == "mismatch"
    assert any("Condition mismatch" in r for r in res.reasons)


def test_storage_variant_mismatch():
    subject = {
        "title": "Apple iPhone 15 (128 GB) - Blue",
        "brand": "Apple",
        "model": "iPhone 15",
        "condition": "new",
    }
    candidate = {
        "title": "Apple iPhone 15 (256 GB) - Blue",
        "brand": "Apple",
        "model": "iPhone 15",
        "condition": "new",
    }
    res = match_product(subject, candidate)
    assert res.status == "mismatch"
    assert any("Storage capacity mismatch" in r for r in res.reasons)


def test_accessory_vs_device_mismatch():
    subject = {
        "title": "Apple iPhone 15 128GB Blue",
        "brand": "Apple",
        "condition": "new",
    }
    candidate = {
        "title": "Silicone Case for Apple iPhone 15 - Blue",
        "brand": "Apple",
        "condition": "new",
    }
    res = match_product(subject, candidate)
    assert res.status == "mismatch"
    assert any("Accessory vs device mismatch" in r for r in res.reasons)


def test_pack_quantity_mismatch():
    subject = {
        "title": "Logitech MX Master 3S Wireless Mouse",
        "brand": "Logitech",
        "condition": "new",
    }
    candidate = {
        "title": "Logitech MX Master 3S Wireless Mouse (Pack of 2)",
        "brand": "Logitech",
        "condition": "new",
    }
    res = match_product(subject, candidate)
    assert res.status == "mismatch"
    assert any("Pack quantity mismatch" in r for r in res.reasons)


def test_insufficient_signals_results_in_uncertain():
    # Only partial title, missing GTIN, missing MPN
    subject = {
        "title": "Wireless Bluetooth Mouse",
        "brand": None,
        "condition": "new",
    }
    candidate = {
        "title": "Wireless Optical Mouse 2.4G",
        "brand": None,
        "condition": "new",
    }
    res = match_product(subject, candidate)
    assert res.status == "uncertain"
