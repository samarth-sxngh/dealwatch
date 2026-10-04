"""Notification repository for managing alert dispatch and deduplication."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Notification)

    async def create_notification_if_unique(
        self,
        tracker_id: uuid.UUID,
        type: str,
        deduplication_key: str,
        payload: dict[str, Any],
        offer_id: uuid.UUID | None = None,
    ) -> Notification | None:
        """Inserts a notification record only if the deduplication key has not been seen.

        Returns the newly created Notification or None if duplicate.
        """
        notif_id = uuid.uuid4()
        now = datetime.now(UTC)
        stmt = (
            insert(Notification)
            .values(
                id=notif_id,
                tracker_id=tracker_id,
                offer_id=offer_id,
                type=type,
                deduplication_key=deduplication_key,
                payload=payload,
                status="pending",
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["deduplication_key"])
        )
        res = await self.session.execute(stmt)
        await self.session.flush()

        if res.rowcount == 0:
            # Duplicate alert suppressed by unique key
            return None

        return await self.get_by_id(notif_id)

    async def get_pending_notifications(self, limit: int = 50) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.status == "pending")
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_sent(self, notification_id: uuid.UUID) -> None:
        notif = await self.get_by_id(notification_id)
        if notif:
            notif.status = "sent"
            notif.sent_at = datetime.now(UTC)
            await self.session.flush()

    async def mark_failed(self, notification_id: uuid.UUID, error_message: str) -> None:
        notif = await self.get_by_id(notification_id)
        if notif:
            notif.status = "failed"
            notif.error_message = error_message
            await self.session.flush()
