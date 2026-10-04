"""Tracking service for managing user 14-day price tracking jobs and authorization isolation."""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.offer_repository import OfferRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.tracker_repository import TrackerRepository

logger = logging.getLogger(__name__)


class QuotaExceededError(ValueError):
    """Raised when user exceeds active tracker quota."""


class TrackerNotFoundError(ValueError):
    """Raised when tracker does not exist or user lacks permission."""


def _get_product_title(tracker: Any) -> str:
    subject = getattr(tracker, "subject", None)
    if subject and getattr(subject, "product_details", None) and subject.product_details:
        return subject.product_details.title or "Product"
    return "Product"


class TrackingService:
    """Service enforcing tracker lifecycles, user quotas, and multi-tenant data isolation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tracker_repo = TrackerRepository(session)
        self.subject_repo = SubjectRepository(session)
        self.offer_repo = OfferRepository(session)

    async def track_product(
        self,
        user_id: uuid.UUID | str,
        subject_id: uuid.UUID | str,
        offer_ids: list[uuid.UUID | str],
        target_price: Decimal | float | None = None,
        target_currency: str | None = None,
        price_drop_alert: bool = True,
        duration_days: int = 14,
    ) -> dict[str, Any]:
        """Creates a new 14-day tracking job for a user, enforcing max active tracker quota."""
        uid = uuid.UUID(str(user_id)) if isinstance(user_id, str) else user_id
        sid = uuid.UUID(str(subject_id)) if isinstance(subject_id, str) else subject_id

        # 1. Enforce active tracker limit per user
        active_count = await self.tracker_repo.count_active_trackers_for_user(uid)
        if active_count >= settings.MAX_ACTIVE_TRACKERS_PER_USER:
            raise QuotaExceededError(
                f"Active tracker limit reached ({settings.MAX_ACTIVE_TRACKERS_PER_USER} max). "
                "Stop an existing tracker before creating a new one."
            )

        # 2. Verify Subject exists
        subject = await self.subject_repo.get_by_id_with_details(sid)
        if not subject:
            raise ValueError(f"Subject '{subject_id}' not found.")

        # 3. Create Tracker
        dec_target = Decimal(str(target_price)) if target_price is not None else None
        tracker = await self.tracker_repo.create_tracker(
            user_id=uid,
            subject_id=sid,
            duration_days=duration_days,
            check_interval_hours=settings.CHECK_INTERVAL_HOURS,
            target_price=dec_target,
            target_currency=target_currency,
            price_drop_alert=price_drop_alert,
        )

        # 4. Attach tracked offers
        clean_offer_ids = [
            uuid.UUID(str(oid)) if isinstance(oid, str) else oid for oid in offer_ids
        ]
        if clean_offer_ids:
            await self.tracker_repo.attach_offers_to_tracker(
                tracker_id=tracker.id,
                offer_ids=clean_offer_ids,
                original_offer_id=clean_offer_ids[0],
            )

        return {
            "tracker_id": str(tracker.id),
            "subject_id": str(tracker.subject_id),
            "status": tracker.status,
            "duration_days": tracker.duration_days,
            "expires_at": tracker.expires_at.isoformat(),
            "target_price": float(tracker.target_price)
            if tracker.target_price is not None
            else None,
            "target_currency": tracker.target_currency,
            "price_drop_alert": tracker.price_drop_alert,
            "tracked_offers_count": len(clean_offer_ids),
        }

    async def update_tracker(
        self,
        user_id: uuid.UUID | str,
        tracker_id: uuid.UUID | str,
        price_drop_alert: bool | None = None,
        target_price: Decimal | float | None = None,
    ) -> dict[str, Any]:
        """Updates tracker settings, enforcing strict tenant isolation."""
        uid = uuid.UUID(str(user_id)) if isinstance(user_id, str) else user_id
        tid = uuid.UUID(str(tracker_id)) if isinstance(tracker_id, str) else tracker_id

        tracker = await self.tracker_repo.get_user_tracker(uid, tid, load_relations=False)
        if not tracker:
            raise TrackerNotFoundError(f"Tracker '{tracker_id}' not found or access denied.")

        if price_drop_alert is not None:
            tracker.price_drop_alert = price_drop_alert
        if target_price is not None:
            tracker.target_price = Decimal(str(target_price))

        tracker.updated_at = datetime.now(UTC)
        await self.session.flush()

        return {
            "tracker_id": str(tracker.id),
            "status": tracker.status,
            "target_price": float(tracker.target_price)
            if tracker.target_price is not None
            else None,
            "price_drop_alert": tracker.price_drop_alert,
        }

    async def stop_tracking(
        self,
        user_id: uuid.UUID | str,
        tracker_id: uuid.UUID | str,
    ) -> dict[str, Any]:
        """Stops an active tracker immediately, enforcing tenant isolation."""
        uid = uuid.UUID(str(user_id)) if isinstance(user_id, str) else user_id
        tid = uuid.UUID(str(tracker_id)) if isinstance(tracker_id, str) else tracker_id

        tracker = await self.tracker_repo.get_user_tracker(uid, tid, load_relations=False)
        if not tracker:
            raise TrackerNotFoundError(f"Tracker '{tracker_id}' not found or access denied.")

        tracker.status = "stopped"
        tracker.updated_at = datetime.now(UTC)
        await self.session.flush()

        return {
            "tracker_id": str(tracker.id),
            "status": tracker.status,
            "stopped_at": tracker.updated_at.isoformat(),
        }

    async def get_tracking_status(
        self,
        user_id: uuid.UUID | str,
        tracker_id: uuid.UUID | str,
    ) -> dict[str, Any]:
        """Returns tracking status and monitored offers, strictly isolated by user_id."""
        uid = uuid.UUID(str(user_id)) if isinstance(user_id, str) else user_id
        tid = uuid.UUID(str(tracker_id)) if isinstance(tracker_id, str) else tracker_id

        tracker = await self.tracker_repo.get_user_tracker(uid, tid)
        if not tracker:
            raise TrackerNotFoundError(f"Tracker '{tracker_id}' not found or access denied.")

        offers_info = []
        for tracked_offer in tracker.tracked_offers:
            off = tracked_offer.offer
            offers_info.append(
                {
                    "offer_id": str(off.id),
                    "retailer": off.source.name,
                    "url": off.url_or_deeplink,
                    "price": float(off.total_price) if off.total_price is not None else None,
                    "currency": off.currency,
                    "availability": off.availability,
                    "is_original": tracked_offer.is_original,
                }
            )

        return {
            "tracker_id": str(tracker.id),
            "subject_id": str(tracker.subject_id),
            "product_title": _get_product_title(tracker),
            "status": tracker.status,
            "created_at": tracker.created_at.isoformat(),
            "expires_at": tracker.expires_at.isoformat(),
            "last_checked_at": tracker.last_checked_at.isoformat()
            if tracker.last_checked_at
            else None,
            "target_price": float(tracker.target_price)
            if tracker.target_price is not None
            else None,
            "target_currency": tracker.target_currency,
            "price_drop_alert": tracker.price_drop_alert,
            "tracked_offers": offers_info,
        }

    async def list_trackers(self, user_id: uuid.UUID | str) -> list[dict[str, Any]]:
        """Lists all trackers for a user with tenant isolation."""
        uid = uuid.UUID(str(user_id)) if isinstance(user_id, str) else user_id
        trackers = await self.tracker_repo.list_active_trackers_for_user(uid)

        results = []
        for t in trackers:
            results.append(
                {
                    "tracker_id": str(t.id),
                    "subject_id": str(t.subject_id),
                    "product_title": _get_product_title(t),
                    "status": t.status,
                    "expires_at": t.expires_at.isoformat(),
                    "target_price": float(t.target_price) if t.target_price is not None else None,
                    "price_drop_alert": t.price_drop_alert,
                    "tracked_offers_count": len(t.tracked_offers),
                }
            )
        return results
