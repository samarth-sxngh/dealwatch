"""Integration and unit tests for services and repositories.

Tests ProductService, DealService, TrackingService, PriceService,
and NotificationService including tenant isolation, quotas, and alert deduplication.
"""

import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.rules import (
    make_price_drop_dedup_key,
)
from app.providers.base import FetchResult
from app.providers.fetcher import fetcher
from app.repositories.notification_repository import NotificationRepository
from app.repositories.observation_repository import ObservationRepository
from app.repositories.offer_repository import OfferRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.tracker_repository import TrackerRepository
from app.repositories.user_repository import UserRepository
from app.services.deal_service import DealService
from app.services.notification_service import NotificationService
from app.services.price_service import PriceService
from app.services.product_service import ProductService
from app.services.tracking_service import (
    QuotaExceededError,
    TrackerNotFoundError,
    TrackingService,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_fixture(filename: str) -> str:
    path = FIXTURES_DIR / filename
    return path.read_text(encoding="utf-8")


# ==============================================================================
# 1. ProductService Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_product_service_identify_from_url_success(db_session: AsyncSession):
    html_content = read_fixture("croma_iphone.html")
    mock_url = "https://www.croma.com/apple-iphone-15-128gb-blue-/p/300652"

    mock_result = FetchResult(
        url=mock_url,
        status_code=200,
        content=html_content,
        content_type="text/html; charset=utf-8",
        is_success=True,
    )

    product_service = ProductService(db_session)

    with patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=mock_result):
        data = await product_service.identify_product(source_url=mock_url)

    assert data["title"] == "Apple iPhone 15 (128GB, Blue)"
    assert data["brand"] == "Apple"
    assert data["market_country"] == "IN"
    assert data["currency"] == "INR"
    assert data["observed_price"] == 71990.0
    assert data["availability"] == "in_stock"
    assert data["match_status"] == "exact"
    assert data["subject_id"] is not None
    assert data["offer_id"] is not None

    # Verify database persistence
    subject_repo = SubjectRepository(db_session)
    subject = await subject_repo.get_by_id_with_details(data["subject_id"])
    assert subject is not None
    assert subject.product_details.gtin == "0194253782910"
    assert subject.product_details.mpn == "MTP43HN/A"

    offer_repo = OfferRepository(db_session)
    offer = await offer_repo.get_by_id(data["offer_id"])
    assert offer is not None
    assert offer.total_price == Decimal("71990.00")
    assert offer.currency == "INR"

    obs_repo = ObservationRepository(db_session)
    history = await obs_repo.get_for_offer(offer.id)
    assert len(history) >= 1
    assert history[0].total_price == Decimal("71990.00")


@pytest.mark.asyncio
async def test_product_service_identify_from_query(db_session: AsyncSession):
    product_service = ProductService(db_session)
    data = await product_service.identify_product(product_query="Sony WH-1000XM5")

    assert data["title"] == "Sony WH-1000XM5"
    assert data["market_confidence"] == "needs_input"
    assert "Which country" in data["clarification_prompt"]
    assert data["observed_price"] is None
    assert data["subject_id"] is not None

    subject_repo = SubjectRepository(db_session)
    subject = await subject_repo.get_by_id_with_details(data["subject_id"])
    assert subject is not None
    assert subject.normalized_key == "query:sony wh-1000xm5"


@pytest.mark.asyncio
async def test_product_service_validation_errors(db_session: AsyncSession):
    product_service = ProductService(db_session)

    # Neither URL nor query
    with pytest.raises(ValueError, match="Either source_url or product_query must be provided"):
        await product_service.identify_product()

    # Failed fetch
    failed_result = FetchResult(
        url="https://www.croma.com/p/123",
        status_code=500,
        content="",
        content_type="text/html",
        is_success=False,
        error_message="HTTP 500 Internal Server Error",
    )
    with (
        patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=failed_result),
        pytest.raises(ValueError, match="Failed to fetch product page"),
    ):
        await product_service.identify_product(source_url="https://www.croma.com/p/123")


# ==============================================================================
# 2. DealService Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_deal_service_find_deals_ordering_and_separation(db_session: AsyncSession):
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    deal_service = DealService(db_session)

    # Create Subject
    subject = await subject_repo.create_product_subject(
        normalized_key=f"product:apple_iphone15_128gb-{uuid.uuid4().hex[:6]}",
        title="Apple iPhone 15 128GB",
        brand="Apple",
        model="iPhone 15",
    )

    # Source 1: Croma
    source_croma = await source_repo.get_or_create(
        domain="croma.com", name="Croma", country="IN", currency="INR"
    )
    # Source 2: Reliance Digital
    source_reliance = await source_repo.get_or_create(
        domain="reliancedigital.in", name="Reliance Digital", country="IN", currency="INR"
    )
    # Source 3: Unverified third-party
    source_market = await source_repo.get_or_create(
        domain="unverified.com", name="UnverifiedSeller", country="IN", currency="INR"
    )

    # Offer 1: Exact match @ 71,990 INR
    await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source_croma.id,
        canonical_url="https://www.croma.com/apple-iphone-15/p/1",
        currency="INR",
        total_price=Decimal("71990.00"),
        match_status="exact",
    )

    # Offer 2: Exact match @ 69,990 INR (Cheaper verified deal!)
    await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source_reliance.id,
        canonical_url="https://www.reliancedigital.in/apple-iphone-15/p/2",
        currency="INR",
        total_price=Decimal("69990.00"),
        match_status="exact",
    )

    # Offer 3: Uncertain match @ 50,000 INR (Must NOT be ranked as cheapest verified!)
    await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source_market.id,
        canonical_url="https://www.unverified.com/iphone-case/p/3",
        currency="INR",
        total_price=Decimal("50000.00"),
        match_status="uncertain",
        match_reasons=["Possible accessory or variant mismatch"],
    )

    result = await deal_service.find_deals(subject.id)

    # Lowest verified price MUST be 69,990 (not 50,000)
    assert result["lowest_verified_price"] == 69990.0
    assert result["lowest_verified_retailer"] == "Reliance Digital"
    assert result["verified_offers_count"] == 2
    assert result["uncertain_offers_count"] == 1

    # Verified offers sorted by price ascending
    assert result["verified_offers"][0]["total_price"] == 69990.0
    assert result["verified_offers"][1]["total_price"] == 71990.0

    # Uncertain offers separated
    assert result["uncertain_offers"][0]["total_price"] == 50000.0
    assert result["uncertain_offers"][0]["match_status"] == "uncertain"


@pytest.mark.asyncio
async def test_deal_service_submit_offer_url_exact_and_mismatch(db_session: AsyncSession):
    subject_repo = SubjectRepository(db_session)
    deal_service = DealService(db_session)

    # Existing Subject with GTIN
    subject = await subject_repo.create_product_subject(
        normalized_key=f"gtin:0194253782910-{uuid.uuid4().hex[:6]}",
        title="Apple iPhone 15 (128GB, Blue)",
        brand="Apple",
        model="iPhone 15",
        variant="128GB",
        gtin="0194253782910",
        mpn="MTP43HN/A",
    )

    # 1. Matching competitor submission
    croma_html = read_fixture("croma_iphone.html")
    match_result = FetchResult(
        url="https://www.croma.com/apple-iphone-15-128gb-blue-/p/300652",
        status_code=200,
        content=croma_html,
        content_type="text/html",
        is_success=True,
    )

    with patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=match_result):
        res = await deal_service.submit_offer_url(
            subject_id=subject.id,
            url="https://www.croma.com/apple-iphone-15-128gb-blue-/p/300652",
        )

    assert res["accepted"] is True
    assert res["match_status"] == "exact"
    assert res["matched_on"] == "gtin"
    assert res["observed_price"] == 71990.0

    # 2. Mismatching competitor submission (e.g. refurbished product)
    refurb_html = read_fixture("refurbished.html")
    mismatch_result = FetchResult(
        url="https://www.bhphotovideo.com/c/product/123-refurb",
        status_code=200,
        content=refurb_html,
        content_type="text/html",
        is_success=True,
    )

    with patch.object(fetcher, "fetch", new_callable=AsyncMock, return_value=mismatch_result):
        res_mismatch = await deal_service.submit_offer_url(
            subject_id=subject.id,
            url="https://www.bhphotovideo.com/c/product/123-refurb",
        )

    assert res_mismatch["accepted"] is False
    assert res_mismatch["match_status"] == "mismatch"


# ==============================================================================
# 3. TrackingService Tests (Quotas & Tenant Isolation)
# ==============================================================================


@pytest.mark.asyncio
async def test_tracking_service_quota_enforcement(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    tracking_service = TrackingService(db_session)

    user = await user_repo.get_or_create(oauth_sub=f"quota-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"prod-{uuid.uuid4().hex[:6]}",
        title="Test Headphones",
    )
    source = await source_repo.get_or_create(
        domain="amazon.in", name="Amazon", country="IN", currency="INR"
    )
    offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source.id,
        canonical_url=f"https://www.amazon.in/dp/{uuid.uuid4().hex[:10]}",
        currency="INR",
        total_price=Decimal("15000.00"),
        match_status="exact",
    )

    created_tracker_ids = []
    # Create up to MAX_ACTIVE_TRACKERS_PER_USER (5)
    for _ in range(settings.MAX_ACTIVE_TRACKERS_PER_USER):
        tracker = await tracking_service.track_product(
            user_id=user.id,
            subject_id=subject.id,
            offer_ids=[offer.id],
            target_price=14000.0,
            target_currency="INR",
        )
        created_tracker_ids.append(tracker["tracker_id"])

    # 6th attempt must raise QuotaExceededError
    with pytest.raises(QuotaExceededError, match="Active tracker limit reached"):
        await tracking_service.track_product(
            user_id=user.id,
            subject_id=subject.id,
            offer_ids=[offer.id],
        )

    # Stop one tracker -> quota freed!
    await tracking_service.stop_tracking(user_id=user.id, tracker_id=created_tracker_ids[0])

    # Now a new tracker should succeed
    new_tracker = await tracking_service.track_product(
        user_id=user.id,
        subject_id=subject.id,
        offer_ids=[offer.id],
    )
    assert new_tracker["status"] == "active"


@pytest.mark.asyncio
async def test_tracking_service_multi_tenant_authorization_isolation(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    tracking_service = TrackingService(db_session)

    user_a = await user_repo.get_or_create(oauth_sub=f"user-a-{uuid.uuid4().hex[:6]}")
    user_b = await user_repo.get_or_create(oauth_sub=f"user-b-{uuid.uuid4().hex[:6]}")

    subject = await subject_repo.create_product_subject(
        normalized_key=f"tenant-subject-{uuid.uuid4().hex[:6]}",
        title="Isolated Product",
    )
    source = await source_repo.get_or_create(
        domain="flipkart.com", name="Flipkart", country="IN", currency="INR"
    )
    offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source.id,
        canonical_url=f"https://www.flipkart.com/p/{uuid.uuid4().hex[:10]}",
        currency="INR",
        total_price=Decimal("20000.00"),
        match_status="exact",
    )

    # User A creates a tracker
    tracker_a = await tracking_service.track_product(
        user_id=user_a.id,
        subject_id=subject.id,
        offer_ids=[offer.id],
        target_price=18000.0,
        target_currency="INR",
    )
    tracker_id_a = tracker_a["tracker_id"]

    # 1. User B CANNOT read User A's tracker
    with pytest.raises(TrackerNotFoundError):
        await tracking_service.get_tracking_status(user_id=user_b.id, tracker_id=tracker_id_a)

    # 2. User B CANNOT modify User A's tracker
    with pytest.raises(TrackerNotFoundError):
        await tracking_service.update_tracker(
            user_id=user_b.id,
            tracker_id=tracker_id_a,
            target_price=10000.0,
        )

    # 3. User B CANNOT stop User A's tracker
    with pytest.raises(TrackerNotFoundError):
        await tracking_service.stop_tracking(user_id=user_b.id, tracker_id=tracker_id_a)

    # 4. User B listing trackers sees empty list
    user_b_trackers = await tracking_service.list_trackers(user_id=user_b.id)
    assert len(user_b_trackers) == 0

    # User A sees their own tracker
    user_a_trackers = await tracking_service.list_trackers(user_id=user_a.id)
    assert len(user_a_trackers) == 1
    assert user_a_trackers[0]["tracker_id"] == tracker_id_a


# ==============================================================================
# 4. PriceService Tests (Integrity & History)
# ==============================================================================


@pytest.mark.asyncio
async def test_price_service_record_check_preserves_price_on_failure(db_session: AsyncSession):
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    price_service = PriceService(db_session)

    subject = await subject_repo.create_product_subject(
        normalized_key=f"price-sub-{uuid.uuid4().hex[:6]}",
        title="Camera Lens",
    )
    source = await source_repo.get_or_create(
        domain="croma.com", name="Croma", country="IN", currency="INR"
    )
    offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source.id,
        canonical_url=f"https://www.croma.com/p/{uuid.uuid4().hex[:10]}",
        currency="INR",
        total_price=Decimal("45000.00"),
        match_status="exact",
    )

    # 1. Record successful check
    await price_service.record_check_result(
        offer_id=offer.id,
        check_run_id="run-success-01",
        currency="INR",
        total_price=Decimal("43000.00"),
        availability="in_stock",
        price_status="ok",
    )

    # Offer price updated
    updated_offer = await offer_repo.get_by_id(offer.id)
    assert updated_offer.total_price == Decimal("43000.00")
    assert updated_offer.price_status == "ok"

    # 2. Record failed check (e.g. retailer returned 503 or CAPTCHA)
    await price_service.record_check_result(
        offer_id=offer.id,
        check_run_id="run-fail-02",
        currency="INR",
        total_price=None,
        availability="unknown",
        price_status="unavailable",
    )

    # Critical rule: previous valid price (43000.00) is NEVER destroyed or overwritten with None!
    final_offer = await offer_repo.get_by_id(offer.id)
    assert final_offer.total_price == Decimal("43000.00")
    assert final_offer.price_status == "unavailable"

    # Both observations recorded in history (ordered newest first)
    history = await price_service.get_price_history(offer.id)
    assert len(history) == 2
    assert history[0]["check_run_id"] == "run-fail-02"
    assert history[0]["total_price"] is None
    assert history[0]["price_status"] == "unavailable"
    assert history[1]["check_run_id"] == "run-success-01"
    assert history[1]["total_price"] == 43000.0
    assert history[1]["price_status"] == "ok"


# ==============================================================================
# 5. NotificationService Tests (Alerts & Unique Deduplication Keys)
# ==============================================================================


@pytest.mark.asyncio
async def test_notification_service_price_drop_and_deduplication(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    tracker_repo = TrackerRepository(db_session)
    notif_repo = NotificationRepository(db_session)
    notif_service = NotificationService(db_session)

    user = await user_repo.get_or_create(oauth_sub=f"notif-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"notif-sub-{uuid.uuid4().hex[:6]}",
        title="Smart Television",
    )
    source = await source_repo.get_or_create(
        domain="amazon.in", name="Amazon", country="IN", currency="INR"
    )
    offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source.id,
        canonical_url=f"https://www.amazon.in/dp/{uuid.uuid4().hex[:10]}",
        currency="INR",
        total_price=Decimal("40000.00"),
        availability="in_stock",
        match_status="exact",
    )
    tracker = await tracker_repo.create_tracker(
        user_id=user.id,
        subject_id=subject.id,
        price_drop_alert=True,
    )

    # 1. Price drops from 40,000 to 35,000 INR
    alerts = await notif_service.evaluate_offer_alerts(
        tracker=tracker,
        offer=offer,
        prev_price=Decimal("40000.00"),
        curr_price=Decimal("35000.00"),
        check_date="2026-10-04",
    )

    assert len(alerts) == 1
    assert alerts[0]["type"] == "price_drop"
    expected_key = make_price_drop_dedup_key(
        tracker_id=tracker.id,
        offer_id=offer.id,
        new_price=Decimal("35000.00"),
        currency="INR",
        check_date="2026-10-04",
    )
    assert alerts[0]["key"] == expected_key

    # Pending notification stored in DB
    pending = await notif_repo.get_pending_notifications()
    matching_notifs = [n for n in pending if n.deduplication_key == expected_key]
    assert len(matching_notifs) == 1

    # 2. Re-evaluation on the same day with same price drop must be suppressed!
    duplicate_alerts = await notif_service.evaluate_offer_alerts(
        tracker=tracker,
        offer=offer,
        prev_price=Decimal("40000.00"),
        curr_price=Decimal("35000.00"),
        check_date="2026-10-04",
    )
    assert len(duplicate_alerts) == 0


@pytest.mark.asyncio
async def test_notification_service_target_reached_and_competitor_cheaper(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    source_repo = SourceRepository(db_session)
    offer_repo = OfferRepository(db_session)
    tracker_repo = TrackerRepository(db_session)
    notif_service = NotificationService(db_session)

    user = await user_repo.get_or_create(oauth_sub=f"target-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"target-sub-{uuid.uuid4().hex[:6]}",
        title="Laptop 16GB",
    )
    source_orig = await source_repo.get_or_create(
        domain="amazon.in", name="Amazon", country="IN", currency="INR"
    )
    source_comp = await source_repo.get_or_create(
        domain="flipkart.com", name="Flipkart", country="IN", currency="INR"
    )

    orig_offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source_orig.id,
        canonical_url=f"https://www.amazon.in/dp/{uuid.uuid4().hex[:10]}",
        currency="INR",
        total_price=Decimal("60000.00"),
        availability="in_stock",
        match_status="exact",
    )
    comp_offer = await offer_repo.save_or_update_offer(
        subject_id=subject.id,
        source_id=source_comp.id,
        canonical_url=f"https://www.flipkart.com/p/{uuid.uuid4().hex[:10]}",
        currency="INR",
        total_price=Decimal("54000.00"),
        availability="in_stock",
        match_status="exact",
    )

    # Tracker with target price 55,000 INR
    tracker = await tracker_repo.create_tracker(
        user_id=user.id,
        subject_id=subject.id,
        target_price=Decimal("55000.00"),
        target_currency="INR",
    )

    # Competitor evaluated at 54,000 INR (reaches target AND is cheaper than original!)
    alerts = await notif_service.evaluate_offer_alerts(
        tracker=tracker,
        offer=comp_offer,
        prev_price=Decimal("58000.00"),
        curr_price=Decimal("54000.00"),
        check_date="2026-10-04",
        original_offer=orig_offer,
    )

    alert_types = {a["type"] for a in alerts}
    assert "target_reached" in alert_types
    assert "competitor_cheaper" in alert_types


@pytest.mark.asyncio
async def test_notification_service_tracking_expired_alert(db_session: AsyncSession):
    user_repo = UserRepository(db_session)
    subject_repo = SubjectRepository(db_session)
    tracker_repo = TrackerRepository(db_session)
    notif_service = NotificationService(db_session)

    user = await user_repo.get_or_create(oauth_sub=f"expired-user-{uuid.uuid4().hex[:6]}")
    subject = await subject_repo.create_product_subject(
        normalized_key=f"expired-sub-{uuid.uuid4().hex[:6]}",
        title="Gaming Monitor",
    )
    tracker = await tracker_repo.create_tracker(
        user_id=user.id,
        subject_id=subject.id,
        duration_days=14,
    )

    # First call generates alert
    success = await notif_service.queue_tracking_expired_alert(tracker)
    assert success is True

    # Second call suppressed by dedup key
    duplicate = await notif_service.queue_tracking_expired_alert(tracker)
    assert duplicate is False
