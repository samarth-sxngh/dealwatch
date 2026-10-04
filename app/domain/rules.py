"""Price comparison, alert evaluation rules, and deduplication key generation."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.domain.money import CurrencyMismatchError, Money


@dataclass(frozen=True)
class PriceDropEvaluation:
    is_alertable: bool
    drop_amount: Money | None
    reason: str


@dataclass(frozen=True)
class TargetPriceEvaluation:
    is_alertable: bool
    current_price: Money
    target_price: Money
    reason: str


@dataclass(frozen=True)
class CompetitorAlertEvaluation:
    is_alertable: bool
    original_price: Money
    competitor_price: Money
    savings: Money | None
    comparison_basis: Literal["total_price", "base_price"]
    message: str | None


def evaluate_price_drop(
    prev_price: Money | None,
    curr_price: Money | None,
    is_available: bool,
    price_status: str = "ok",
) -> PriceDropEvaluation:
    """Evaluates whether an observed price drop triggers an alert.

    Rules:
    - Same currency strictly required.
    - Current price < Previous price (even 1 unit drop).
    - Equal or higher price = no alert.
    - Missing, failed, or out of stock = no alert.
    """
    if price_status != "ok":
        return PriceDropEvaluation(
            is_alertable=False,
            drop_amount=None,
            reason=f"Check price_status is '{price_status}', not 'ok'.",
        )

    if not is_available:
        return PriceDropEvaluation(
            is_alertable=False,
            drop_amount=None,
            reason="Offer is currently out of stock or unavailable.",
        )

    if prev_price is None or curr_price is None:
        return PriceDropEvaluation(
            is_alertable=False,
            drop_amount=None,
            reason="Previous or current price is missing.",
        )

    try:
        if curr_price >= prev_price:
            return PriceDropEvaluation(
                is_alertable=False,
                drop_amount=None,
                reason=f"Current price {curr_price} is not less than previous price {prev_price}.",
            )

        drop = prev_price - curr_price
        return PriceDropEvaluation(
            is_alertable=True,
            drop_amount=drop,
            reason=f"Price dropped by {drop} from {prev_price} to {curr_price}.",
        )
    except CurrencyMismatchError as exc:
        return PriceDropEvaluation(
            is_alertable=False,
            drop_amount=None,
            reason=f"Currency mismatch prevented price drop comparison: {exc!s}",
        )


def evaluate_target_price(
    target_price: Money,
    curr_price: Money | None,
    is_available: bool,
    price_status: str = "ok",
) -> TargetPriceEvaluation:
    """Evaluates whether current price reaches or beats user's target price threshold.

    Rules:
    - Same currency required.
    - Current price <= Target price.
    - Offer must be in stock.
    """
    if price_status != "ok" or not is_available or curr_price is None:
        return TargetPriceEvaluation(
            is_alertable=False,
            current_price=curr_price or target_price,
            target_price=target_price,
            reason="Offer is unavailable or current price is not ok.",
        )

    try:
        if curr_price <= target_price:
            return TargetPriceEvaluation(
                is_alertable=True,
                current_price=curr_price,
                target_price=target_price,
                reason=f"Target reached: {curr_price} <= {target_price}.",
            )
        else:
            return TargetPriceEvaluation(
                is_alertable=False,
                current_price=curr_price,
                target_price=target_price,
                reason=f"Current price {curr_price} is above target {target_price}.",
            )
    except CurrencyMismatchError as exc:
        return TargetPriceEvaluation(
            is_alertable=False,
            current_price=curr_price,
            target_price=target_price,
            reason=f"Currency mismatch prevented target comparison: {exc!s}",
        )


def evaluate_competitor_comparison(
    original_source_name: str,
    original_price: Money,
    original_has_full_total: bool,
    competitor_source_name: str,
    competitor_price: Money,
    competitor_has_full_total: bool,
    competitor_match_status: str,
    competitor_is_available: bool,
) -> CompetitorAlertEvaluation:
    """Evaluates if a competitor offer is cheaper than the original tracked offer.

    Rules:
    - Competitor match_status must be 'exact'. Uncertain matches are never alerted.
    - Competitor must be in stock.
    - Total price used only when shipping/tax known for both; else base price used.
    """
    basis: Literal["total_price", "base_price"] = (
        "total_price" if (original_has_full_total and competitor_has_full_total) else "base_price"
    )

    if competitor_match_status != "exact":
        return CompetitorAlertEvaluation(
            is_alertable=False,
            original_price=original_price,
            competitor_price=competitor_price,
            savings=None,
            comparison_basis=basis,
            message="Competitor match certainty is not exact.",
        )

    if not competitor_is_available:
        return CompetitorAlertEvaluation(
            is_alertable=False,
            original_price=original_price,
            competitor_price=competitor_price,
            savings=None,
            comparison_basis=basis,
            message="Competitor is out of stock.",
        )

    try:
        if competitor_price < original_price:
            diff = original_price - competitor_price
            basis_str = (
                "total price"
                if basis == "total_price"
                else "item price (excluding unknown fees/tax)"
            )
            msg = (
                f"{competitor_source_name} {competitor_price} is cheaper than "
                f"{original_source_name} ({original_price}) by {diff} ({basis_str})."
            )
            return CompetitorAlertEvaluation(
                is_alertable=True,
                original_price=original_price,
                competitor_price=competitor_price,
                savings=diff,
                comparison_basis=basis,
                message=msg,
            )
        return CompetitorAlertEvaluation(
            is_alertable=False,
            original_price=original_price,
            competitor_price=competitor_price,
            savings=None,
            comparison_basis=basis,
            message=f"{competitor_source_name} is not cheaper than {original_source_name}.",
        )
    except CurrencyMismatchError as exc:
        return CompetitorAlertEvaluation(
            is_alertable=False,
            original_price=original_price,
            competitor_price=competitor_price,
            savings=None,
            comparison_basis=basis,
            message=f"Currency mismatch prevented competitor comparison: {exc!s}",
        )


# Deduplication Key Generators
def make_price_drop_dedup_key(
    tracker_id: uuid.UUID | str,
    offer_id: uuid.UUID | str,
    new_price: Decimal | str,
    currency: str,
    check_date: date | str,
) -> str:
    """Generates unique deduplication key for price drop alert."""
    price_str = f"{Decimal(str(new_price)):.2f}"
    return f"tracker:{tracker_id}:offer:{offer_id}:price_drop:{price_str}:{currency.upper()}:{check_date}"


def make_target_reached_dedup_key(
    tracker_id: uuid.UUID | str,
    target_price: Decimal | str,
    currency: str,
) -> str:
    """Generates unique deduplication key for target reached alert (dedup per tracker)."""
    price_str = f"{Decimal(str(target_price)):.2f}"
    return f"tracker:{tracker_id}:target_reached:{price_str}:{currency.upper()}"


def make_competitor_cheaper_dedup_key(
    tracker_id: uuid.UUID | str,
    competitor_offer_id: uuid.UUID | str,
    new_price: Decimal | str,
    currency: str,
    check_date: date | str,
) -> str:
    """Generates unique deduplication key for competitor cheaper alert."""
    price_str = f"{Decimal(str(new_price)):.2f}"
    return f"tracker:{tracker_id}:competitor:{competitor_offer_id}:cheaper:{price_str}:{currency.upper()}:{check_date}"


def make_tracking_expired_dedup_key(
    tracker_id: uuid.UUID | str,
) -> str:
    """Generates unique deduplication key for tracking expiry alert (sent once)."""
    return f"tracker:{tracker_id}:tracking_expired"
