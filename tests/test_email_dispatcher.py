"""Tests for Phase 9: Brevo Transactional Email Alert Dispatcher.

Covers responsive email templates, Brevo API client, error handling,
database notification lifecycle (pending -> sent / failed), and user preferences.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.context import set_current_auth
from app.auth.models import TokenPayload
from app.database import async_session_factory
from app.main import app
from app.models.notification import Notification, NotificationPreference
from app.models.tracker import Tracker
from app.providers.email.brevo import BrevoAPIError, BrevoNotifier
from app.providers.email.templates import (
    render_competitor_cheaper_email,
    render_email_alert,
    render_price_drop_email,
    render_target_reached_email,
    render_tracking_expired_email,
)
from app.repositories.offer_repository import OfferRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.user_repository import UserRepository
from app.services.email_dispatcher import EmailDispatcherService


# -----------------------------------------------------------------------------
# 1. Template Rendering Tests
# -----------------------------------------------------------------------------
def test_render_price_drop_template():
    payload = {
        "product_title": "Sony WH-1000XM5 Headphones",
        "retailer": "Amazon",
        "previous_price": "29990.00",
        "new_price": "24990.00",
        "currency": "INR",
        "drop_amount": "5000.00",
        "url": "https://www.amazon.in/dp/B09XS7JWHH",
    }
    subject, html, text = render_price_drop_email(payload)

    assert "Price Drop Alert" in subject
    assert "24990.00" in subject
    assert "Amazon" in subject

    assert "Sony WH-1000XM5 Headphones" in html
    assert "24990.00" in html
    assert "29990.00" in html
    assert "5000.00" in html
    assert "https://www.amazon.in/dp/B09XS7JWHH" in html
    assert "View Deal on Amazon" in html

    assert "Sony WH-1000XM5 Headphones" in text
    assert "24990.00" in text


def test_render_target_reached_template():
    payload = {
        "product_title": "MacBook Air M3",
        "retailer": "Croma",
        "target_price": "100000.00",
        "current_price": "98990.00",
        "currency": "INR",
        "url": "https://www.croma.com/p/12345",
    }
    subject, html, _text = render_target_reached_email(payload)

    assert "Target Price Reached" in subject
    assert "98990.00" in subject
    assert "MacBook Air M3" in html
    assert "100000.00" in html
    assert "98990.00" in html
    assert "Croma" in html
    assert "https://www.croma.com/p/12345" in html


def test_render_competitor_cheaper_template():
    payload = {
        "product_title": "iPhone 15",
        "competitor_retailer": "Croma",
        "original_retailer": "Amazon",
        "savings": "3000.00",
        "currency": "INR",
        "message": "Croma is currently cheaper by INR 3000.00!",
        "url": "https://www.croma.com/p/iphone15",
    }
    subject, html, text = render_competitor_cheaper_email(payload)

    assert "Cheaper Competitor Found" in subject
    assert "3000.00" in subject
    assert "Croma" in subject
    assert "iPhone 15" in html
    assert "Amazon" in html
    assert "INR 3000.00" in text


def test_render_tracking_expired_template():
    payload = {
        "product_title": "Gaming Monitor 27-inch",
        "message": "Your 14-day price tracking period has completed.",
    }
    subject, html, text = render_tracking_expired_email(payload)

    assert "14-Day Price Tracking Completed" in subject
    assert "Gaming Monitor 27-inch" in subject
    assert "Gaming Monitor 27-inch" in html
    assert "completed" in text


def test_render_email_alert_generic_fallback():
    subject, html, text = render_email_alert("unknown_type", {"message": "Custom event triggered"})
    assert "DealWatch Alert" in subject
    assert "Custom event triggered" in html
    assert "Custom event triggered" in text


# -----------------------------------------------------------------------------
# 2. Brevo Notifier Unit Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_brevo_notifier_dry_run_when_no_api_key():
    """When BREVO_API_KEY is None, notifier logs and simulates dispatch without errors."""
    notifier = BrevoNotifier(api_key="")
    res = await notifier.send_transactional_email(
        recipient_email="user@example.com",
        subject="Test Alert",
        html_content="<p>Test</p>",
        text_content="Test",
    )
    assert res.get("simulated") is True
    assert "messageId" in res


@pytest.mark.asyncio
async def test_brevo_notifier_successful_dispatch():
    """Mocking Brevo API 201 Created response."""
    notifier = BrevoNotifier(api_key="valid-brevo-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"messageId": "<brevo-test-msg-id-12345>"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await notifier.send_transactional_email(
            recipient_email="shopper@example.com",
            subject="Price dropped!",
            html_content="<h1>Deal Alert</h1>",
            text_content="Deal Alert",
        )

    assert res["messageId"] == "<brevo-test-msg-id-12345>"


@pytest.mark.asyncio
async def test_brevo_notifier_api_error():
    """Brevo returns 400 Bad Request (e.g. sender email not verified)."""
    notifier = BrevoNotifier(api_key="valid-brevo-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "code": "invalid_parameter",
        "message": "Sender email is not verified in your Brevo account.",
    }

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp),
        pytest.raises(BrevoAPIError) as exc_info,
    ):
        await notifier.send_transactional_email(
            recipient_email="shopper@example.com",
            subject="Price dropped!",
            html_content="<h1>Deal Alert</h1>",
            text_content="Deal Alert",
        )

    assert exc_info.value.status_code == 400
    assert "Sender email is not verified" in exc_info.value.message


@pytest.mark.asyncio
async def test_brevo_notifier_network_timeout():
    """Network connection failure communicating with Brevo."""
    notifier = BrevoNotifier(api_key="valid-brevo-key")

    with (
        patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectTimeout("Timeout"),
        ),
        pytest.raises(BrevoAPIError) as exc_info,
    ):
        await notifier.send_transactional_email(
            recipient_email="shopper@example.com",
            subject="Price dropped!",
            html_content="<h1>Deal Alert</h1>",
            text_content="Deal Alert",
        )
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_brevo_notifier_base_notifier_send_method():
    """BaseNotifier.send(...) renders alert templates and returns boolean success status."""
    notifier = BrevoNotifier(api_key="mock-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"messageId": "<msg-1>"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        ok = await notifier.send(
            recipient="shopper@example.com",
            subject="",
            message="Price dropped",
            payload={
                "type": "price_drop",
                "product_title": "Kindle",
                "retailer": "Amazon",
                "previous_price": "9999",
                "new_price": "7999",
                "currency": "INR",
            },
        )
    assert ok is True

    # When API throws error, send() catches and returns False
    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Network fail"),
    ):
        fail_ok = await notifier.send(
            recipient="shopper@example.com",
            subject="",
            message="Fail",
            payload={"type": "price_drop"},
        )
    assert fail_ok is False


# -----------------------------------------------------------------------------
# 3. Email Dispatcher Service & Database Lifecycle
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_pending_notifications_lifecycle():
    """Tests end-to-end database lifecycle: Notification pending -> sent with timestamp."""
    user_email = f"buyer-{uuid.uuid4().hex[:6]}@example.com"

    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        subject_repo = SubjectRepository(session)
        source_repo = SourceRepository(session)
        offer_repo = OfferRepository(session)

        # 1. Create entities
        user = await user_repo.get_or_create(
            oauth_sub=f"sub-{uuid.uuid4().hex[:6]}", email=user_email
        )
        subject = await subject_repo.create_product_subject(
            normalized_key=f"mail-test-{uuid.uuid4().hex[:6]}",
            title="Noise Cancelling Earbuds",
        )
        source = await source_repo.get_or_create(
            domain="amazon.in", name="Amazon", country="IN", currency="INR"
        )
        offer = await offer_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source.id,
            canonical_url=f"https://www.amazon.in/dp/{uuid.uuid4().hex[:8]}",
            currency="INR",
            total_price=Decimal("4999.00"),
            match_status="exact",
        )

        tracker = Tracker(
            user_id=user.id,
            subject_id=subject.id,
            status="active",
            duration_days=14,
            expires_at=datetime.now(UTC),
            check_interval_hours=24,
            target_price=Decimal("4500.00"),
            target_currency="INR",
        )
        session.add(tracker)
        await session.flush()

        # Notification queued in pending status
        notif = Notification(
            tracker_id=tracker.id,
            offer_id=offer.id,
            type="price_drop",
            deduplication_key=f"dedup-{uuid.uuid4().hex}",
            payload={
                "product_title": "Noise Cancelling Earbuds",
                "retailer": "Amazon",
                "previous_price": "5999.00",
                "new_price": "4999.00",
                "currency": "INR",
                "drop_amount": "1000.00",
                "url": offer.url_or_deeplink,
            },
            status="pending",
        )
        session.add(notif)
        await session.commit()
        notif_id = notif.id

    # 2. Dispatch pending notifications
    mock_notifier = MagicMock(spec=BrevoNotifier)
    mock_notifier.send_transactional_email = AsyncMock(
        return_value={"messageId": "<delivered-123>"}
    )

    async with async_session_factory() as session:
        dispatcher = EmailDispatcherService(session, notifier=mock_notifier)
        summary = await dispatcher.dispatch_pending(limit=10)
        await session.commit()

    assert summary["sent"] >= 1
    assert mock_notifier.send_transactional_email.called
    called_kwargs = mock_notifier.send_transactional_email.call_args.kwargs
    assert called_kwargs["recipient_email"] == user_email
    assert "Price Drop Alert" in called_kwargs["subject"]

    # 3. Verify database record status updated to 'sent'
    async with async_session_factory() as session:
        updated_notif = await session.get(Notification, notif_id)
        assert updated_notif is not None
        assert updated_notif.status == "sent"
        assert updated_notif.sent_at is not None
        assert updated_notif.error_message is None


@pytest.mark.asyncio
async def test_dispatch_failed_marks_notification_as_failed():
    """When Brevo rejects the email, status becomes 'failed' with error_message."""
    user_email = f"failed-user-{uuid.uuid4().hex[:6]}@example.com"

    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        subject_repo = SubjectRepository(session)

        user = await user_repo.get_or_create(
            oauth_sub=f"sub-{uuid.uuid4().hex[:6]}", email=user_email
        )
        subject = await subject_repo.create_product_subject(
            normalized_key=f"fail-sub-{uuid.uuid4().hex[:6]}",
            title="Failing Item",
        )
        tracker = Tracker(
            user_id=user.id,
            subject_id=subject.id,
            status="active",
            duration_days=14,
            expires_at=datetime.now(UTC),
            check_interval_hours=24,
        )
        session.add(tracker)
        await session.flush()

        notif = Notification(
            tracker_id=tracker.id,
            type="price_drop",
            deduplication_key=f"dedup-{uuid.uuid4().hex}",
            payload={"product_title": "Failing Item", "currency": "INR", "new_price": "100"},
            status="pending",
        )
        session.add(notif)
        await session.commit()
        notif_id = notif.id

    mock_notifier = MagicMock(spec=BrevoNotifier)
    mock_notifier.send_transactional_email = AsyncMock(
        side_effect=BrevoAPIError(400, "Unverified sender email address in Brevo account.")
    )

    async with async_session_factory() as session:
        dispatcher = EmailDispatcherService(session, notifier=mock_notifier)
        summary = await dispatcher.dispatch_pending(limit=10)
        await session.commit()

    assert summary["failed"] >= 1

    async with async_session_factory() as session:
        updated = await session.get(Notification, notif_id)
        assert updated is not None
        assert updated.status == "failed"
        assert "Unverified sender" in updated.error_message


@pytest.mark.asyncio
async def test_dispatch_respects_user_disabled_preference():
    """When User has email_enabled=False in NotificationPreference, notification is skipped."""
    user_email = f"optout-{uuid.uuid4().hex[:6]}@example.com"

    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        subject_repo = SubjectRepository(session)

        user = await user_repo.get_or_create(
            oauth_sub=f"sub-{uuid.uuid4().hex[:6]}", email=user_email
        )
        # Disable emails on existing preference using async select
        stmt_pref = select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        pref = (await session.execute(stmt_pref)).scalar_one_or_none()
        if pref:
            pref.email_enabled = False
            await session.flush()

        subject = await subject_repo.create_product_subject(
            normalized_key=f"optout-sub-{uuid.uuid4().hex[:6]}",
            title="Optout Item",
        )
        tracker = Tracker(
            user_id=user.id,
            subject_id=subject.id,
            status="active",
            duration_days=14,
            expires_at=datetime.now(UTC),
            check_interval_hours=24,
        )
        session.add(tracker)
        await session.flush()

        notif = Notification(
            tracker_id=tracker.id,
            type="price_drop",
            deduplication_key=f"dedup-{uuid.uuid4().hex}",
            payload={"product_title": "Optout Item"},
            status="pending",
        )
        session.add(notif)
        await session.commit()
        notif_id = notif.id

    mock_notifier = MagicMock(spec=BrevoNotifier)
    mock_notifier.send_transactional_email = AsyncMock()

    async with async_session_factory() as session:
        dispatcher = EmailDispatcherService(session, notifier=mock_notifier)
        summary = await dispatcher.dispatch_pending(limit=10)
        await session.commit()

    # Email was skipped, not sent through Brevo
    assert summary["skipped"] >= 1
    assert not mock_notifier.send_transactional_email.called

    async with async_session_factory() as session:
        updated = await session.get(Notification, notif_id)
        assert updated.status == "sent"


# -----------------------------------------------------------------------------
# 4. API Endpoints
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_dispatch_pending_endpoint():
    """POST /api/v1/notifications/dispatch-pending returns 200 with dispatch summary."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.post("/api/v1/notifications/dispatch-pending?limit=5")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "summary" in data
        assert "total_pending" in data["summary"]


@pytest.mark.asyncio
async def test_api_notification_preferences_management():
    """GET & PUT /api/v1/notifications/preferences manages user email settings."""
    sub_key = f"pref-sub-{uuid.uuid4().hex[:6]}"
    email_val = f"{sub_key}@example.com"
    token = TokenPayload(sub=sub_key, email=email_val)
    uid = uuid.uuid4()
    set_current_auth(token, uid)

    async with (
        async_session_factory() as session,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client,
    ):
        user_repo = UserRepository(session)
        user = await user_repo.get_or_create(oauth_sub=sub_key, email=email_val)
        await session.commit()
        set_current_auth(token, user.id)

        # 1. Get default preferences (email_enabled=True)
        get_res = await client.get("/api/v1/notifications/preferences")
        assert get_res.status_code == 200
        assert get_res.json()["email_enabled"] is True

        # 2. Update preferences to False
        put_res = await client.put(
            "/api/v1/notifications/preferences",
            json={"email_enabled": False},
        )
        assert put_res.status_code == 200
        assert put_res.json()["email_enabled"] is False

        # 3. Verify persisted state
        verify_res = await client.get("/api/v1/notifications/preferences")
        assert verify_res.status_code == 200
        assert verify_res.json()["email_enabled"] is False

    set_current_auth(None, None)
