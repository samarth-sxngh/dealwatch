"""Standalone daily price checker worker for DealWatch.

Designed to execute via GitHub Actions cron or manual invocation.
Uses PostgreSQL distributed lease locking (SKIP LOCKED) to coordinate
batch processing and prevent concurrent worker collisions.
"""

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.logging_config import setup_logging
from app.models.offer import Offer
from app.models.tracker import TrackedOffer, Tracker
from app.providers.extractor import extractor
from app.providers.fetcher import fetcher
from app.providers.retailers.registry import retailer_registry
from app.repositories.tracker_repository import TrackerRepository
from app.services.email_dispatcher import EmailDispatcherService
from app.services.notification_service import BaseNotifier, NotificationService
from app.services.price_service import PriceService

logger = logging.getLogger(__name__)


class PriceCheckerWorker:
    """Worker handling scheduled price updates, expirations, and alert evaluations."""

    def __init__(self, session: AsyncSession, notifier: BaseNotifier | None = None) -> None:
        self.session = session
        self.tracker_repo = TrackerRepository(session)
        self.price_service = PriceService(session)
        self.notification_service = NotificationService(session, notifier=notifier)

    async def expire_old_trackers(self) -> int:
        """Finds and expires active trackers older than their 14-day duration."""
        expired_trackers = await self.tracker_repo.list_expired_active_trackers()
        count = 0
        for tracker in expired_trackers:
            try:
                tracker.status = "expired"
                tracker.updated_at = datetime.now(UTC)
                await self.notification_service.queue_tracking_expired_alert(tracker)
                count += 1
                logger.info(
                    "Expired tracker %s for subject %s",
                    tracker.id,
                    tracker.subject_id,
                )
            except Exception as e:  # noqa: BLE001
                logger.error("Failed expiring tracker %s: %s", tracker.id, e)

        if count > 0:
            await self.session.flush()
        return count

    async def check_single_offer(
        self,
        tracker: Tracker,
        tracked_offer: TrackedOffer,
        original_offer: Offer | None,
        check_run_id: str,
        check_date: str,
    ) -> dict[str, Any]:
        """Fetches latest page, records observation, and evaluates alerts for one offer."""
        offer = tracked_offer.offer
        if not offer or not offer.url_or_deeplink:
            return {"status": "missing_offer", "alerts_queued": 0}

        canonical_url = offer.url_or_deeplink

        # 1. SSRF-safe page fetch
        fetch_res = await fetcher.fetch(canonical_url)
        if not fetch_res.is_success:
            logger.warning(
                "Fetch failed for offer %s (%s): %s",
                offer.id,
                canonical_url,
                fetch_res.error_message,
            )
            # Record failed observation without erasing existing prices
            await self.price_service.record_check_result(
                offer_id=offer.id,
                check_run_id=check_run_id,
                currency=offer.currency,
                total_price=None,
                availability="unknown",
                price_status="unavailable",
            )
            return {"status": "fetch_failed", "alerts_queued": 0}

        # 2. Extract structured pricing
        adapter = retailer_registry.get_adapter_for_url(canonical_url)
        extracted = adapter.extract(fetch_res.content, canonical_url) if adapter else None
        if not extracted:
            extracted = extractor.extract(fetch_res.content, base_url=canonical_url)

        if (
            not extracted
            or not extracted.primary_offer
            or extracted.primary_offer.total_price is None
        ):
            logger.warning(
                "Could not extract valid price for offer %s (%s)",
                offer.id,
                canonical_url,
            )
            await self.price_service.record_check_result(
                offer_id=offer.id,
                check_run_id=check_run_id,
                currency=offer.currency,
                total_price=None,
                availability="unknown",
                price_status="unavailable",
            )
            return {"status": "price_unavailable", "alerts_queued": 0}

        # 3. Successful extraction -> record observation and evaluate alerts
        primary = extracted.primary_offer
        prev_price = offer.total_price
        curr_price = primary.total_price
        currency = primary.currency or offer.currency

        await self.price_service.record_check_result(
            offer_id=offer.id,
            check_run_id=check_run_id,
            currency=currency,
            base_price=primary.base_price,
            total_price=curr_price,
            fees=primary.fees,
            taxes=primary.taxes,
            availability=primary.availability,
            price_status="ok",
        )

        alerts = await self.notification_service.evaluate_offer_alerts(
            tracker=tracker,
            offer=offer,
            prev_price=prev_price,
            curr_price=curr_price,
            check_date=check_date,
            original_offer=original_offer,
        )

        return {"status": "success", "alerts_queued": len(alerts)}

    async def run(
        self,
        lease_seconds: int = 600,
        batch_size: int = 50,
        dispatch_emails: bool = False,
    ) -> dict[str, Any]:
        """Runs one full scheduled checking cycle over due and expired trackers."""
        logger.info("Starting PriceCheckerWorker execution cycle...")
        summary = {
            "expired_trackers": 0,
            "checked_trackers": 0,
            "checked_offers": 0,
            "alerts_queued": 0,
            "failed_offers": 0,
            "emails_dispatched": 0,
            "emails_failed": 0,
        }

        # 1. Process 14-day tracking expirations
        summary["expired_trackers"] = await self.expire_old_trackers()

        # 2. Claim due trackers with distributed lease lock
        cutoff = datetime.now(UTC) - timedelta(hours=settings.CHECK_INTERVAL_HOURS)
        due_trackers = await self.tracker_repo.claim_due_trackers(
            cutoff=cutoff,
            lease_seconds=lease_seconds,
            limit=batch_size,
        )

        if not due_trackers:
            logger.info("No active trackers due for checking.")
            return summary

        summary["checked_trackers"] = len(due_trackers)
        logger.info("Claimed %d due tracker(s) for checking.", len(due_trackers))

        now_utc = datetime.now(UTC)
        check_date = now_utc.date().isoformat()

        # 3. Check each tracker
        for tracker in due_trackers:
            check_run_id = f"chk-{now_utc.strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:6]}"
            original_offer = next(
                (to.offer for to in tracker.tracked_offers if to.is_original), None
            )

            try:
                for tracked_offer in tracker.tracked_offers:
                    summary["checked_offers"] += 1
                    try:
                        res = await self.check_single_offer(
                            tracker=tracker,
                            tracked_offer=tracked_offer,
                            original_offer=original_offer,
                            check_run_id=check_run_id,
                            check_date=check_date,
                        )
                        summary["alerts_queued"] += res["alerts_queued"]
                        if res["status"] != "success":
                            summary["failed_offers"] += 1
                    except Exception as offer_err:  # noqa: BLE001
                        logger.error(
                            "Unexpected error checking offer %s: %s",
                            tracked_offer.offer_id,
                            offer_err,
                        )
                        summary["failed_offers"] += 1
            finally:
                # Always release distributed lease lock even if an offer fails
                await self.tracker_repo.release_tracker_lock(
                    tracker_id=tracker.id,
                    last_checked_at=datetime.now(UTC),
                )

        # 4. Dispatch generated email alerts via Brevo if enabled
        if dispatch_emails and summary["alerts_queued"] > 0:
            try:
                dispatcher = EmailDispatcherService(self.session)
                dispatch_res = await dispatcher.dispatch_pending()
                summary["emails_dispatched"] = dispatch_res.get("sent", 0)
                summary["emails_failed"] = dispatch_res.get("failed", 0)
            except Exception as mail_err:  # noqa: BLE001
                logger.error("Failed dispatching alert emails: %s", mail_err)

        logger.info(
            "PriceCheckerWorker cycle finished: checked %d trackers, %d offers (%d failed), %d alerts queued, %d emails sent.",
            summary["checked_trackers"],
            summary["checked_offers"],
            summary["failed_offers"],
            summary["alerts_queued"],
            summary["emails_dispatched"],
        )
        return summary


async def main() -> None:
    """CLI entrypoint for executing scheduled check runs."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("DealWatch Price Checker Worker launching...")

    async with async_session_factory() as session:
        try:
            worker = PriceCheckerWorker(session)
            results = await worker.run()
            await session.commit()
            logger.info("Worker completed successfully: %s", results)
        except Exception:
            await session.rollback()
            logger.exception("Price Checker Worker crashed")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
