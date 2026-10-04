"""Integration and unit tests for the scheduled PriceCheckerWorker."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.base import FetchResult
from app.providers.fetcher import fetcher
from app.repositories.notification_repository import NotificationRepository
from app.repositories.observation_repository import ObservationRepository
from app.repositories.offer_repository import OfferRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.tracker_repository import TrackerRepository
from app.repositories.user_repository import UserRepository
from app.workers.price_checker import PriceCheckerWorker

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_worker_processes_due_trackers_and_detects_price_drop(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    tracker_repo = TrackerRepository(db_session)
    notif_repo = NotificationRepository(db_session)

    # 1. Setup user, subject, source, offer, tracker
    user = await user_repo.get_or_create(oauth_sub=f"worker-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"worker-sub-{uuid.uuid4().hex[:6]}",
        title="Apple iPhone 15",
    )
    source = await source_repo.get_or_create(
        domain="croma.com", name="Croma", country="IN", currency="INR"
    )

    # Initial offer at 75,000 INR
    offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source.id,
        canonical_url="https://www.croma.com/apple-iphone-15-128gb-blue-/p/300652",
        currency="INR",
        total_price=Decimal("75000.00"),
        availability="in_stock",
        match_status="exact",
    )

    # Active tracker with due check (last_checked_at is 25 hours ago)
    past_checked = datetime.now(UTC) - timedelta(hours=25)
    tracker = await tracker_repo.create_tracker(
        user_id=user.id,
        subject_id=subject.id,
        price_drop_alert=True,
    )
    tracker.last_checked_at = past_checked
    await db_session.flush()

    await tracker_repo.attach_offers_to_tracker(
        tracker_id=tracker.id,
        offer_ids=[offer.id],
        original_offer_id=offer.id,
    )

    # 2. Mock page fetch returning fixture with price 71,990 INR (a 3,010 INR price drop!)
    croma_html = read_fixture("croma_iphone.html")
    mock_res = FetchResult(
        url="https://www.croma.com/apple-iphone-15-128gb-blue-/p/300652",
        status_code=200,
        content=croma_html,
        content_type="text/html",
        is_success=True,
    )

    worker = PriceCheckerWorker(db_session)
    with patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=mock_res):
        summary = await worker.run()

    # 3. Assertions
    assert summary["checked_trackers"] == 1
    assert summary["checked_offers"] == 1
    assert summary["alerts_queued"] == 1
    assert summary["failed_offers"] == 0

    # Offer price updated
    updated_offer = await offer_repo.get_by_id(offer.id)
    assert updated_offer.total_price == Decimal("71990.00")

    # Alert queued in pending notifications
    pending = await notif_repo.get_pending_notifications()
    drop_alerts = [n for n in pending if n.tracker_id == tracker.id and n.type == "price_drop"]
    assert len(drop_alerts) == 1
    assert drop_alerts[0].payload["previous_price"] == "75000.00"
    assert drop_alerts[0].payload["new_price"] == "71990.00"

    # Tracker lease lock released and last_checked_at updated to recent
    refreshed_tracker = await tracker_repo.get_by_id(tracker.id)
    assert refreshed_tracker.locked_until is None
    assert refreshed_tracker.last_checked_at > past_checked


@pytest.mark.asyncio
async def test_worker_distributed_lease_locking_skips_concurrent_worker(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    tracker_repo = TrackerRepository(db_session)

    user = await user_repo.get_or_create(oauth_sub=f"lock-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"lock-sub-{uuid.uuid4().hex[:6]}",
        title="Test Monitor",
    )
    source = await source_repo.get_or_create(
        domain="bhphotovideo.com", name="BHPhoto", country="US", currency="USD"
    )
    offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source.id,
        canonical_url="https://www.bhphotovideo.com/c/product/123",
        currency="USD",
        total_price=Decimal("300.00"),
        match_status="exact",
    )

    tracker = await tracker_repo.create_tracker(
        user_id=user.id,
        subject_id=subject.id,
    )
    tracker.last_checked_at = datetime.now(UTC) - timedelta(hours=25)
    await db_session.flush()

    await tracker_repo.attach_offers_to_tracker(
        tracker_id=tracker.id,
        offer_ids=[offer.id],
    )

    # Worker 1 claims due trackers with 10-minute lease
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    claimed_by_w1 = await tracker_repo.claim_due_trackers(cutoff=cutoff, lease_seconds=600)
    assert len(claimed_by_w1) == 1
    assert claimed_by_w1[0].id == tracker.id

    # Concurrent Worker 2 attempts to claim -> must return 0 because tracker is locked!
    claimed_by_w2 = await tracker_repo.claim_due_trackers(cutoff=cutoff, lease_seconds=600)
    assert len(claimed_by_w2) == 0

    # Worker 1 releases lock
    await tracker_repo.release_tracker_lock(tracker.id, last_checked_at=datetime.now(UTC))


@pytest.mark.asyncio
async def test_worker_handles_failed_fetch_gracefully(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    tracker_repo = TrackerRepository(db_session)
    obs_repo = ObservationRepository(db_session)

    user = await user_repo.get_or_create(oauth_sub=f"fail-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"fail-sub-{uuid.uuid4().hex[:6]}",
        title="Smart Speaker",
    )
    source = await source_repo.get_or_create(
        domain="croma.com", name="Croma", country="IN", currency="INR"
    )
    offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source.id,
        canonical_url="https://www.croma.com/p/speaker",
        currency="INR",
        total_price=Decimal("4999.00"),
        availability="in_stock",
        match_status="exact",
    )

    tracker = await tracker_repo.create_tracker(user_id=user.id, subject_id=subject.id)
    tracker.last_checked_at = datetime.now(UTC) - timedelta(hours=25)
    await db_session.flush()

    await tracker_repo.attach_offers_to_tracker(
        tracker_id=tracker.id,
        offer_ids=[offer.id],
    )

    # Mock fetch failure (e.g. HTTP 503 or bot block)
    failed_res = FetchResult(
        url="https://www.croma.com/p/speaker",
        status_code=503,
        content="",
        content_type="text/html",
        is_success=False,
        error_message="Service Unavailable (503)",
    )

    worker = PriceCheckerWorker(db_session)
    with patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=failed_res):
        summary = await worker.run()

    assert summary["checked_trackers"] == 1
    assert summary["failed_offers"] == 1

    # CRITICAL: previous valid price 4999.00 is preserved, NOT erased!
    current_offer = await offer_repo.get_by_id(offer.id)
    assert current_offer.total_price == Decimal("4999.00")
    assert current_offer.price_status == "unavailable"

    # Observation recorded with unavailable status
    history = await obs_repo.get_for_offer(offer.id)
    assert len(history) >= 1
    assert history[0].price_status == "unavailable"


@pytest.mark.asyncio
async def test_worker_expires_old_trackers(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    tracker_repo = TrackerRepository(db_session)
    notif_repo = NotificationRepository(db_session)

    user = await user_repo.get_or_create(oauth_sub=f"exp-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"exp-sub-{uuid.uuid4().hex[:6]}",
        title="Old Tracker Subject",
    )

    # Tracker created with expires_at in the past
    tracker = await tracker_repo.create_tracker(user_id=user.id, subject_id=subject.id)
    tracker.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.flush()

    worker = PriceCheckerWorker(db_session)
    summary = await worker.run()

    assert summary["expired_trackers"] == 1

    # Verify tracker status changed to expired
    refreshed = await tracker_repo.get_by_id(tracker.id)
    assert refreshed.status == "expired"

    # Verify expiration notification queued
    pending = await notif_repo.get_pending_notifications()
    exp_alerts = [n for n in pending if n.tracker_id == tracker.id and n.type == "tracking_expired"]
    assert len(exp_alerts) == 1
