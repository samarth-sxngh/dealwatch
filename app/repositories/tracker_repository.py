"""Tracker repository for managing 14-day price tracking jobs and tracked offers."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.offer import Offer
from app.models.subject import Subject
from app.models.tracker import TrackedOffer, Tracker
from app.repositories.base import BaseRepository


class TrackerRepository(BaseRepository[Tracker]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Tracker)

    async def get_user_tracker(self, user_id: uuid.UUID, tracker_id: uuid.UUID) -> Tracker | None:
        """Retrieves a tracker enforcing strict tenant isolation on user_id."""
        stmt = (
            select(Tracker)
            .options(
                selectinload(Tracker.subject).selectinload(Subject.product_details),
                selectinload(Tracker.tracked_offers)
                .selectinload(TrackedOffer.offer)
                .selectinload(Offer.source),
            )
            .where(Tracker.id == tracker_id, Tracker.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_active_trackers_for_user(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count(Tracker.id)).where(
            Tracker.user_id == user_id, Tracker.status == "active"
        )
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)

    async def list_active_trackers_for_user(self, user_id: uuid.UUID) -> list[Tracker]:
        stmt = (
            select(Tracker)
            .options(
                selectinload(Tracker.subject).selectinload(Subject.product_details),
                selectinload(Tracker.tracked_offers)
                .selectinload(TrackedOffer.offer)
                .selectinload(Offer.source),
            )
            .where(Tracker.user_id == user_id)
            .order_by(Tracker.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_tracker(
        self,
        user_id: uuid.UUID,
        subject_id: uuid.UUID,
        duration_days: int = 14,
        check_interval_hours: int = 24,
        target_price: Decimal | None = None,
        target_currency: str | None = None,
        price_drop_alert: bool = True,
    ) -> Tracker:
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=duration_days)

        tracker = Tracker(
            id=uuid.uuid4(),
            user_id=user_id,
            subject_id=subject_id,
            status="active",
            duration_days=duration_days,
            expires_at=expires_at,
            check_interval_hours=check_interval_hours,
            target_price=target_price,
            target_currency=target_currency.upper() if target_currency else None,
            price_drop_alert=price_drop_alert,
            last_checked_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(tracker)
        await self.session.flush()
        return tracker

    async def attach_offers_to_tracker(
        self,
        tracker_id: uuid.UUID,
        offer_ids: list[uuid.UUID],
        original_offer_id: uuid.UUID | None = None,
    ) -> list[TrackedOffer]:
        tracked_records: list[TrackedOffer] = []
        for oid in offer_ids:
            rec = TrackedOffer(
                id=uuid.uuid4(),
                tracker_id=tracker_id,
                offer_id=oid,
                is_original=(oid == original_offer_id),
            )
            self.session.add(rec)
            tracked_records.append(rec)

        await self.session.flush()
        return tracked_records

    async def list_due_trackers(self, cutoff: datetime, limit: int = 50) -> list[Tracker]:
        """Fetches active trackers due for checking that are not expired and not locked."""
        now = datetime.now(UTC)
        stmt = (
            select(Tracker)
            .options(
                selectinload(Tracker.subject).selectinload(Subject.product_details),
                selectinload(Tracker.tracked_offers)
                .selectinload(TrackedOffer.offer)
                .selectinload(Offer.source),
            )
            .where(
                Tracker.status == "active",
                Tracker.expires_at > now,
                or_(Tracker.last_checked_at.is_(None), Tracker.last_checked_at <= cutoff),
                or_(Tracker.locked_until.is_(None), Tracker.locked_until <= now),
            )
            .order_by(Tracker.last_checked_at.asc().nulls_first())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_expired_active_trackers(self, limit: int = 50) -> list[Tracker]:
        """Fetches active trackers whose 14-day tracking period has expired."""
        now = datetime.now(UTC)
        stmt = (
            select(Tracker)
            .options(selectinload(Tracker.subject).selectinload(Subject.product_details))
            .where(Tracker.status == "active", Tracker.expires_at <= now)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def claim_due_trackers(
        self, cutoff: datetime, lease_seconds: int = 600, limit: int = 50
    ) -> list[Tracker]:
        """Claims due active trackers with a distributed lease lock using SKIP LOCKED."""
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)

        subq = (
            select(Tracker.id)
            .where(
                Tracker.status == "active",
                Tracker.expires_at > now,
                or_(Tracker.last_checked_at.is_(None), Tracker.last_checked_at <= cutoff),
                or_(Tracker.locked_until.is_(None), Tracker.locked_until <= now),
            )
            .order_by(Tracker.last_checked_at.asc().nulls_first())
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )

        update_stmt = (
            update(Tracker)
            .where(Tracker.id.in_(subq))
            .values(locked_until=lease_until)
            .returning(Tracker.id)
        )
        res = await self.session.execute(update_stmt)
        claimed_ids = list(res.scalars().all())
        if not claimed_ids:
            return []

        stmt = (
            select(Tracker)
            .options(
                selectinload(Tracker.subject).selectinload(Subject.product_details),
                selectinload(Tracker.tracked_offers)
                .selectinload(TrackedOffer.offer)
                .selectinload(Offer.source),
            )
            .where(Tracker.id.in_(claimed_ids))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return list(result.scalars().all())

    async def release_tracker_lock(
        self, tracker_id: uuid.UUID, last_checked_at: datetime | None = None
    ) -> None:
        """Releases the lease lock and updates last_checked_at."""
        tracker = await self.get_by_id(tracker_id)
        if tracker:
            tracker.locked_until = None
            if last_checked_at:
                tracker.last_checked_at = last_checked_at
            await self.session.flush()
