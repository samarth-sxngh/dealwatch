"""Domain core package for DealWatch."""

from app.domain.market import MarketInfo, detect_market_from_domain, reconcile_market
from app.domain.matching import match_product, match_product_with_llm, normalize_gtin
from app.domain.money import CurrencyMismatchError, Money
from app.domain.rules import (
    CompetitorAlertEvaluation,
    PriceDropEvaluation,
    TargetPriceEvaluation,
    evaluate_competitor_comparison,
    evaluate_price_drop,
    evaluate_target_price,
    make_competitor_cheaper_dedup_key,
    make_price_drop_dedup_key,
    make_target_reached_dedup_key,
    make_tracking_expired_dedup_key,
)
from app.domain.urls import canonicalize_url

__all__ = [
    "CompetitorAlertEvaluation",
    "CurrencyMismatchError",
    "MarketInfo",
    "Money",
    "PriceDropEvaluation",
    "TargetPriceEvaluation",
    "canonicalize_url",
    "detect_market_from_domain",
    "evaluate_competitor_comparison",
    "evaluate_price_drop",
    "evaluate_target_price",
    "make_competitor_cheaper_dedup_key",
    "make_price_drop_dedup_key",
    "make_target_reached_dedup_key",
    "make_tracking_expired_dedup_key",
    "match_product",
    "match_product_with_llm",
    "normalize_gtin",
    "reconcile_market",
]
