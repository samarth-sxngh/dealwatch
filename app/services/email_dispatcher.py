"""Email dispatcher service for processing and sending pending notification alerts."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.notification import Notification
from app.models.tracker import Tracker
from app.models.user import User
from app.providers.email.brevo import BrevoAPIError, BrevoNotifier, brevo_notifier
from app.providers.email.templates import render_email_alert
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)


class EmailDispatcherService:
    """Processes pending alert notifications from the database and dispatches transactional emails."""

    def __init__(
        self,
        session: AsyncSession,
        notifier: BrevoNotifier | None = None,
    ) -> None:
        self.session = session
        self.notifier = notifier or brevo_notifier
        self.notification_repo = NotificationRepository(session)

    async def get_pending_notifications_with_recipients(
        self, limit: int = 50
    ) -> list[Notification]:
        """Fetches pending notifications with tracker, user, and notification preferences eagerly joined."""
        stmt = (
            select(Notification)
            .options(
                joinedload(Notification.tracker)
                .joinedload(Tracker.user)
                .joinedload(User.notification_preference)
            )
            .where(Notification.status == "pending")
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def dispatch_pending(self, limit: int = 50) -> dict[str, Any]:
        """Processes a batch of pending alert notifications.

        Checks user preferences, renders email content, dispatches via Brevo,
        and marks records as sent or failed.

        Returns:
            Dict summarizing processing counts (total, sent, failed, skipped).
        """
        notifications = await self.get_pending_notifications_with_recipients(limit=limit)

        summary = {
            "total_pending": len(notifications),
            "sent": 0,
            "failed": 0,
            "skipped": 0,
        }

        if not notifications:
            logger.info("No pending notifications to dispatch.")
            return summary

        logger.info("Found %d pending notification(s) for email dispatch.", len(notifications))

        for notif in notifications:
            try:
                # 1. Resolve recipient User & Email
                tracker = notif.tracker
                if not tracker or not tracker.user:
                    logger.warning("Notification %s has no associated tracker or user.", notif.id)
                    await self.notification_repo.mark_failed(
                        notif.id, "No associated user found for tracker."
                    )
                    summary["failed"] += 1
                    continue

                user = tracker.user
                recipient_email = user.email
                if not recipient_email:
                    logger.warning(
                        "User %s for notification %s has no email address.",
                        user.id,
                        notif.id,
                    )
                    await self.notification_repo.mark_failed(
                        notif.id, "User has no registered email address."
                    )
                    summary["failed"] += 1
                    continue

                # 2. Check User Notification Preferences
                pref = user.notification_preference
                if pref is not None and not pref.email_enabled:
                    logger.info(
                        "User %s has disabled email notifications. Skipping notification %s.",
                        user.id,
                        notif.id,
                    )
                    await self.notification_repo.mark_sent(notif.id)
                    summary["skipped"] += 1
                    continue

                # 3. Render Subject, HTML, and Text Templates
                subject, html_content, text_content = render_email_alert(
                    alert_type=notif.type,
                    payload=notif.payload,
                )

                # 4. Dispatch Email via Brevo API
                await self.notifier.send_transactional_email(
                    recipient_email=recipient_email,
                    subject=subject,
                    html_content=html_content,
                    text_content=text_content,
                )

                # 5. Mark as Sent
                await self.notification_repo.mark_sent(notif.id)
                summary["sent"] += 1

            except BrevoAPIError as api_err:
                logger.error("Brevo API delivery error for notification %s: %s", notif.id, api_err)
                await self.notification_repo.mark_failed(notif.id, str(api_err))
                summary["failed"] += 1

            except Exception as exc:
                logger.exception("Unexpected error dispatching notification %s", notif.id)
                await self.notification_repo.mark_failed(notif.id, f"Dispatch exception: {exc}")
                summary["failed"] += 1

        logger.info("Email dispatch batch finished: %s", summary)
        return summary
