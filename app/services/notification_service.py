"""Notification service and alert evaluation engine."""

import logging
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.models.offer import Offer
from app.models.tracker import Tracker
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)


class BaseNotifier(ABC):
    """Abstract interface for dispatching notifications across channels."""

    @abstractmethod
    async def send(
        self, recipient: str, subject: str, message: str, payload: dict[str, Any]
    ) -> bool:
        pass


class LoggingNotifier(BaseNotifier):
    """Fallback / development notifier that logs alerts."""

    async def send(
        self, recipient: str, subject: str, message: str, payload: dict[str, Any]
    ) -> bool:
        logger.info(
            "[ALERT] Recipient: %s | Subject: %s | Message: %s", recipient, subject, message
        )
        return True


def _get_product_title(tracker: Tracker) -> str:
    subject = getattr(tracker, "subject", None)
    if subject and getattr(subject, "product_details", None) and subject.product_details:
        return subject.product_details.title or "Product"
    return "Product"


class NotificationService:
    """Service evaluating price observations, generating alerts, and enforcing deduplication."""

    def __init__(self, session: AsyncSession, notifier: BaseNotifier | None = None) -> None:
        self.session = session
        self.notification_repo = NotificationRepository(session)
        self.notifier = notifier or LoggingNotifier()

    async def evaluate_offer_alerts(
        self,
        tracker: Tracker,
        offer: Offer,
        prev_price: Decimal | None,
        curr_price: Decimal | None,
        check_date: date | str,
        original_offer: Offer | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluates price drops, target reaches, and competitor savings.

        Queues notifications with deduplication keys.
        """
        queued_alerts: list[dict[str, Any]] = []

        if curr_price is None:
            return queued_alerts

        curr_money = Money(curr_price, offer.currency)
        is_in_stock = offer.availability == "in_stock"

        # 1. Price Drop Evaluation
        if tracker.price_drop_alert and prev_price is not None:
            prev_money = Money(prev_price, offer.currency)
            eval_drop = evaluate_price_drop(
                prev_price=prev_money,
                curr_price=curr_money,
                is_available=is_in_stock,
                price_status=offer.price_status,
            )
            if eval_drop.is_alertable:
                dedup_key = make_price_drop_dedup_key(
                    tracker_id=tracker.id,
                    offer_id=offer.id,
                    new_price=curr_price,
                    currency=offer.currency,
                    check_date=check_date,
                )
                payload = {
                    "product_title": _get_product_title(tracker),
                    "retailer": offer.source.name,
                    "previous_price": str(prev_price),
                    "new_price": str(curr_price),
                    "currency": offer.currency,
                    "drop_amount": str(eval_drop.drop_amount.amount)
                    if eval_drop.drop_amount
                    else None,
                    "url": offer.url_or_deeplink,
                }
                notif = await self.notification_repo.create_notification_if_unique(
                    tracker_id=tracker.id,
                    offer_id=offer.id,
                    type="price_drop",
                    deduplication_key=dedup_key,
                    payload=payload,
                )
                if notif:
                    queued_alerts.append(
                        {"type": "price_drop", "key": dedup_key, "payload": payload}
                    )

        # 2. Target Price Evaluation
        if (
            tracker.target_price is not None
            and tracker.target_currency
            and tracker.target_currency.upper() == offer.currency.upper()
        ):
            target_money = Money(tracker.target_price, tracker.target_currency)
            eval_target = evaluate_target_price(
                target_price=target_money,
                curr_price=curr_money,
                is_available=is_in_stock,
                price_status=offer.price_status,
            )
            if eval_target.is_alertable:
                dedup_key = make_target_reached_dedup_key(
                    tracker_id=tracker.id,
                    target_price=tracker.target_price,
                    currency=offer.currency,
                )
                payload = {
                    "product_title": _get_product_title(tracker),
                    "retailer": offer.source.name,
                    "target_price": str(tracker.target_price),
                    "current_price": str(curr_price),
                    "currency": offer.currency,
                    "url": offer.url_or_deeplink,
                }
                notif = await self.notification_repo.create_notification_if_unique(
                    tracker_id=tracker.id,
                    offer_id=offer.id,
                    type="target_reached",
                    deduplication_key=dedup_key,
                    payload=payload,
                )
                if notif:
                    queued_alerts.append(
                        {"type": "target_reached", "key": dedup_key, "payload": payload}
                    )

        # 3. Competitor Cheaper Evaluation
        if (
            original_offer
            and original_offer.id != offer.id
            and original_offer.total_price is not None
            and original_offer.currency.upper() == offer.currency.upper()
        ):
            orig_money = Money(original_offer.total_price, original_offer.currency)
            comp_eval = evaluate_competitor_comparison(
                original_source_name=original_offer.source.name,
                original_price=orig_money,
                original_has_full_total=(original_offer.total_price is not None),
                competitor_source_name=offer.source.name,
                competitor_price=curr_money,
                competitor_has_full_total=(offer.total_price is not None),
                competitor_match_status=offer.match_status,
                competitor_is_available=is_in_stock,
            )
            if comp_eval.is_alertable:
                dedup_key = make_competitor_cheaper_dedup_key(
                    tracker_id=tracker.id,
                    competitor_offer_id=offer.id,
                    new_price=curr_price,
                    currency=offer.currency,
                    check_date=check_date,
                )
                payload = {
                    "product_title": _get_product_title(tracker),
                    "message": comp_eval.message,
                    "competitor_retailer": offer.source.name,
                    "original_retailer": original_offer.source.name,
                    "savings": str(comp_eval.savings.amount) if comp_eval.savings else None,
                    "currency": offer.currency,
                    "url": offer.url_or_deeplink,
                }
                notif = await self.notification_repo.create_notification_if_unique(
                    tracker_id=tracker.id,
                    offer_id=offer.id,
                    type="competitor_cheaper",
                    deduplication_key=dedup_key,
                    payload=payload,
                )
                if notif:
                    queued_alerts.append(
                        {"type": "competitor_cheaper", "key": dedup_key, "payload": payload}
                    )

        return queued_alerts

    async def queue_tracking_expired_alert(self, tracker: Tracker) -> bool:
        """Queues a single tracking expiration alert."""
        dedup_key = make_tracking_expired_dedup_key(tracker.id)
        payload = {
            "tracker_id": str(tracker.id),
            "product_title": _get_product_title(tracker),
            "message": "Your 14-day price tracking period has expired. Feel free to re-track any time.",
        }
        notif = await self.notification_repo.create_notification_if_unique(
            tracker_id=tracker.id,
            type="tracking_expired",
            deduplication_key=dedup_key,
            payload=payload,
        )
        return notif is not None
