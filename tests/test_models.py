"""ORM Model unit and integration tests."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Notification,
    NotificationPreference,
    Observation,
    Offer,
    ProductDetails,
    Source,
    Subject,
    TrackedOffer,
    Tracker,
    User,
)


@pytest.mark.asyncio
async def test_full_model_lifecycle(db_session: AsyncSession):
    """Verifies relational model integrity from User to Offer, Observation and Tracker."""
    # 1. User & Preference
    user = User(
        oauth_sub=f"auth0|{uuid.uuid4()}",
        email="testuser@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    pref = NotificationPreference(
        user_id=user.id,
        email_enabled=True,
    )
    db_session.add(pref)
    await db_session.flush()
    assert pref.email_enabled is True

    # 2. Subject & ProductDetails
    subject = Subject(
        vertical="products",
        normalized_key="gtin:194253782910",
        attributes={"category": "electronics"},
    )
    db_session.add(subject)
    await db_session.flush()

    details = ProductDetails(
        subject_id=subject.id,
        title="Apple iPhone 15 (128 GB) - Blue",
        brand="Apple",
        model="iPhone 15",
        variant="128GB Blue",
        gtin="194253782910",
        mpn="MTP43HN/A",
        raw_specs={"storage": "128GB", "color": "Blue"},
    )
    db_session.add(details)
    await db_session.flush()
    assert details.subject_id == subject.id

    # 3. Source (Retailer)
    source = Source(
        vertical="products",
        name="Amazon India",
        country="IN",
        currency="INR",
        domain=f"amazon.in-{uuid.uuid4().hex[:6]}",
        access_tier=2,
        allowed_actions=["fetch_observation", "discover"],
        rate_limit_per_second=0.5,
    )
    db_session.add(source)
    await db_session.flush()

    # 4. Offer
    offer = Offer(
        subject_id=subject.id,
        source_id=source.id,
        url_or_deeplink="https://www.amazon.in/dp/B0CHX1W1XY",
        currency="INR",
        base_price=Decimal("79900.00"),
        fees=Decimal("0.00"),
        taxes=Decimal("0.00"),
        total_price=Decimal("79900.00"),
        availability="in_stock",
        condition="new",
        match_status="exact",
        matched_on="gtin",
        match_reasons=["GTIN 194253782910 verified exact match"],
        price_status="ok",
    )
    db_session.add(offer)
    await db_session.flush()
    assert offer.total_price == Decimal("79900.00")

    # 5. Observation (Point-in-time check history)
    run_id = f"check-{uuid.uuid4()}"
    obs = Observation(
        offer_id=offer.id,
        check_run_id=run_id,
        currency="INR",
        base_price=Decimal("79900.00"),
        total_price=Decimal("79900.00"),
        availability="in_stock",
        price_status="ok",
        raw_data={"scraped_title": "Apple iPhone 15 (128 GB) - Blue"},
    )
    db_session.add(obs)
    await db_session.flush()

    # 6. Tracker & TrackedOffer
    now = datetime.now(UTC)
    tracker = Tracker(
        user_id=user.id,
        subject_id=subject.id,
        status="active",
        duration_days=14,
        expires_at=now + timedelta(days=14),
        check_interval_hours=24,
        target_price=Decimal("75000.00"),
        target_currency="INR",
        price_drop_alert=True,
    )
    db_session.add(tracker)
    await db_session.flush()

    tracked_offer = TrackedOffer(
        tracker_id=tracker.id,
        offer_id=offer.id,
        is_original=True,
    )
    db_session.add(tracked_offer)
    await db_session.flush()

    # 7. Notification with Deduplication Key
    dedup_key = f"tracker:{tracker.id}:offer:{offer.id}:price_drop:74999.00:INR:2026-10-02"
    notif = Notification(
        tracker_id=tracker.id,
        offer_id=offer.id,
        type="price_drop",
        deduplication_key=dedup_key,
        payload={"previous_price": "79900.00", "new_price": "74999.00", "currency": "INR"},
        status="pending",
    )
    db_session.add(notif)
    await db_session.flush()
    assert notif.id is not None


@pytest.mark.asyncio
async def test_observation_unique_run_constraint(db_session: AsyncSession):
    """Verify that retrying a check run on the same offer cannot create duplicate observations."""
    subject = Subject(
        vertical="products",
        normalized_key=f"key-{uuid.uuid4()}",
    )
    source = Source(
        vertical="products",
        name="Test Store",
        country="US",
        currency="USD",
        domain=f"store-{uuid.uuid4().hex[:6]}.com",
        access_tier=2,
    )
    db_session.add_all([subject, source])
    await db_session.flush()

    offer = Offer(
        subject_id=subject.id,
        source_id=source.id,
        url_or_deeplink="https://example.com/product",
        currency="USD",
        total_price=Decimal("199.99"),
    )
    db_session.add(offer)
    await db_session.flush()

    run_id = f"run-{uuid.uuid4()}"
    obs1 = Observation(
        offer_id=offer.id,
        check_run_id=run_id,
        currency="USD",
        total_price=Decimal("199.99"),
    )
    db_session.add(obs1)
    await db_session.flush()

    # Adding second observation with same (offer_id, check_run_id) must fail
    obs2 = Observation(
        offer_id=offer.id,
        check_run_id=run_id,
        currency="USD",
        total_price=Decimal("199.99"),
    )
    db_session.add(obs2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_notification_deduplication_constraint(db_session: AsyncSession):
    """Verify notification deduplication key uniqueness."""
    user = User(oauth_sub=f"auth0|{uuid.uuid4()}")
    subject = Subject(vertical="products", normalized_key=f"key-{uuid.uuid4()}")
    db_session.add_all([user, subject])
    await db_session.flush()

    tracker = Tracker(
        user_id=user.id,
        subject_id=subject.id,
        status="active",
        expires_at=datetime.now(UTC) + timedelta(days=14),
    )
    db_session.add(tracker)
    await db_session.flush()

    unique_key = f"notif-key-{uuid.uuid4()}"
    notif1 = Notification(
        tracker_id=tracker.id,
        type="price_drop",
        deduplication_key=unique_key,
    )
    db_session.add(notif1)
    await db_session.flush()

    notif2 = Notification(
        tracker_id=tracker.id,
        type="price_drop",
        deduplication_key=unique_key,
    )
    db_session.add(notif2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
