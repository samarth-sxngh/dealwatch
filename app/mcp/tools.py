"""Tool implementations for DealWatch MCP Server.

Provides client-agnostic tool handlers serving Claude (readable plain text)
and ChatGPT (structured JSON payloads).
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

from app.auth.context import get_current_user_id
from app.config import settings
from app.database import async_session_factory
from app.repositories.user_repository import UserRepository
from app.services.deal_service import DealService
from app.services.price_service import PriceService
from app.services.product_service import ProductService
from app.services.tracking_service import (
    QuotaExceededError,
    TrackerNotFoundError,
    TrackingService,
)

logger = logging.getLogger(__name__)

# Default demo identity for Phase 7 (No auth first)
# Phase 8 OAuth 2.1 will inject authenticated user IDs from tokens
DEFAULT_UNAUTHENTICATED_USER_SUB = "local-mcp-user"
_CACHED_DEMO_USER_ID: uuid.UUID | None = None


async def get_or_create_default_user_id() -> uuid.UUID:
    """Helper to ensure a local/demo user exists for unauthenticated MCP testing."""
    global _CACHED_DEMO_USER_ID
    if _CACHED_DEMO_USER_ID is not None:
        return _CACHED_DEMO_USER_ID

    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_or_create(
            oauth_sub=DEFAULT_UNAUTHENTICATED_USER_SUB,
            email="user@dealwatch.local",
        )
        await session.commit()
        _CACHED_DEMO_USER_ID = user.id
        return _CACHED_DEMO_USER_ID


async def resolve_effective_user_id() -> uuid.UUID:
    """Resolves the current authenticated user ID from Bearer token context or fallback demo user."""
    user_id = get_current_user_id()
    if user_id is not None:
        return user_id

    if settings.AUTH_REQUIRED:
        raise PermissionError("Authentication required. Please provide a valid Bearer token.")

    return await get_or_create_default_user_id()


async def identify_subject(
    vertical: str = "products",
    url: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Identifies and normalizes a comparison subject from a retailer URL or text query.

    Args:
        vertical: Domain vertical (default: "products").
        url: Direct retailer product URL (e.g. Amazon, Croma, B&H).
        query: Product search query or title (e.g. 'Sony WH-1000XM5').

    Returns:
        Structured subject details, detected market, currency, initial observed price,
        and market clarification prompts if needed.
    """
    if vertical != "products":
        return {
            "error": f"Vertical '{vertical}' is not yet supported. Currently 'products' is active.",
            "supported": False,
        }

    if not url and not query:
        return {
            "error": "Either 'url' or 'query' must be provided.",
            "status": "failed",
        }

    async with async_session_factory() as session:
        try:
            service = ProductService(session)
            result = await service.identify_product(source_url=url, product_query=query)
            await session.commit()
            return {
                "status": "success",
                "vertical": "products",
                **result,
            }
        except Exception as e:
            await session.rollback()
            logger.exception("identify_subject failed")
            return {"status": "error", "message": str(e)}


async def find_offers(
    subject_id: str,
    vertical: str = "products",
    market_country: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Finds verified competitor deals for an identified subject.

    Verified exact matches are sorted lowest-price-first. Uncertain offers
    are separated and flagged with match reasons.

    Args:
        subject_id: Unique Subject UUID from identify_subject.
        vertical: Domain vertical (default: "products").
        market_country: Optional ISO 2-letter country code filter (e.g. 'IN', 'US').
        currency: Optional ISO 3-letter currency code filter (e.g. 'INR', 'USD').

    Returns:
        Lowest verified price, verified offers sorted by price, and separate uncertain offers.
    """
    if vertical != "products":
        return {
            "error": f"Vertical '{vertical}' is not yet supported.",
            "supported": False,
        }

    async with async_session_factory() as session:
        try:
            service = DealService(session)
            result = await service.find_deals(
                subject_id=subject_id,
                market_country=market_country,
                currency=currency,
            )
            await session.commit()
            return {"status": "success", **result}
        except Exception as e:
            await session.rollback()
            logger.exception("find_offers failed")
            return {"status": "error", "message": str(e)}


async def submit_offer_url(
    subject_id: str,
    url: str,
    vertical: str = "products",
) -> dict[str, Any]:
    """Validates and adds a competitor offer URL discovered via web search or user input.

    Fetches the candidate page, extracts structured specs/pricing, and checks exact
    matching criteria (GTIN, MPN, condition, storage, accessories) before admitting it.

    Args:
        subject_id: Unique Subject UUID to compare against.
        url: Competitor retailer product page URL.
        vertical: Domain vertical (default: "products").

    Returns:
        Accepted status (bool), match_status (exact/uncertain/mismatch),
        observed price, currency, and verification explanation.
    """
    if vertical != "products":
        return {"error": f"Vertical '{vertical}' is not yet supported."}

    async with async_session_factory() as session:
        try:
            service = DealService(session)
            result = await service.submit_offer_url(subject_id=subject_id, url=url)
            await session.commit()
            return {"status": "success", **result}
        except Exception as e:
            await session.rollback()
            logger.exception("submit_offer_url failed")
            return {"status": "error", "message": str(e)}


async def track_subject(
    subject_id: str,
    offer_ids: list[str],
    vertical: str = "products",
    target_price: float | None = None,
    target_currency: str | None = None,
    price_drop_alert: bool = True,
    duration_days: int = 14,
) -> dict[str, Any]:
    """Starts a 14-day price tracking job on selected offers for a subject.

    Enforces active tracker quota limit (max 5 active trackers per user).

    Args:
        subject_id: Unique Subject UUID.
        offer_ids: List of verified Offer UUIDs to track daily.
        vertical: Domain vertical (default: "products").
        target_price: Optional target price threshold to trigger an alert.
        target_currency: Target price currency code (e.g. 'INR', 'USD').
        price_drop_alert: Whether to alert on any price drop (default: True).
        duration_days: Tracking window duration in days (default: 14).

    Returns:
        Created Tracker details, expiration date, and tracking status.
    """
    try:
        user_id = await resolve_effective_user_id()
    except PermissionError as e:
        return {"status": "error", "error": "unauthorized", "message": str(e)}

    async with async_session_factory() as session:
        try:
            service = TrackingService(session)
            dec_target = Decimal(str(target_price)) if target_price is not None else None
            result = await service.track_product(
                user_id=user_id,
                subject_id=subject_id,
                offer_ids=offer_ids,
                target_price=dec_target,
                target_currency=target_currency,
                price_drop_alert=price_drop_alert,
                duration_days=duration_days,
            )
            await session.commit()
            return {"status": "success", **result}
        except QuotaExceededError as qe:
            await session.rollback()
            return {
                "status": "quota_exceeded",
                "message": str(qe),
                "suggestion": "You have reached the free-tier limit of 5 active trackers. Stop an existing tracker using stop_tracking to track this item.",
            }
        except Exception as e:
            await session.rollback()
            logger.exception("track_subject failed")
            return {"status": "error", "message": str(e)}


async def update_tracker(
    tracker_id: str,
    target_price: float | None = None,
    price_drop_alert: bool | None = None,
) -> dict[str, Any]:
    """Updates target price threshold or alert settings for an existing tracker.

    Args:
        tracker_id: Unique Tracker UUID.
        target_price: New target price threshold (optional).
        price_drop_alert: Enable/disable alerts on any price drop (optional).

    Returns:
        Updated tracker settings.
    """
    try:
        user_id = await resolve_effective_user_id()
    except PermissionError as e:
        return {"status": "error", "error": "unauthorized", "message": str(e)}

    async with async_session_factory() as session:
        try:
            service = TrackingService(session)
            dec_target = Decimal(str(target_price)) if target_price is not None else None
            result = await service.update_tracker(
                user_id=user_id,
                tracker_id=tracker_id,
                target_price=dec_target,
                price_drop_alert=price_drop_alert,
            )
            await session.commit()
            return {"status": "success", **result}
        except TrackerNotFoundError as tne:
            await session.rollback()
            return {"status": "not_found", "message": str(tne)}
        except Exception as e:
            await session.rollback()
            logger.exception("update_tracker failed")
            return {"status": "error", "message": str(e)}


async def stop_tracking(tracker_id: str) -> dict[str, Any]:
    """Stops an active 14-day price tracking job immediately and frees up tracker quota.

    Args:
        tracker_id: Unique Tracker UUID.

    Returns:
        Confirmation of stopped tracker status.
    """
    try:
        user_id = await resolve_effective_user_id()
    except PermissionError as e:
        return {"status": "error", "error": "unauthorized", "message": str(e)}

    async with async_session_factory() as session:
        try:
            service = TrackingService(session)
            result = await service.stop_tracking(user_id=user_id, tracker_id=tracker_id)
            await session.commit()
            return {"status": "success", **result}
        except TrackerNotFoundError as tne:
            await session.rollback()
            return {"status": "not_found", "message": str(tne)}
        except Exception as e:
            await session.rollback()
            logger.exception("stop_tracking failed")
            return {"status": "error", "message": str(e)}


async def get_tracking_status(tracker_id: str) -> dict[str, Any]:
    """Retrieves current tracking status, days remaining, and monitored offers.

    Args:
        tracker_id: Unique Tracker UUID.

    Returns:
        Product title, tracker status (active/stopped/expired), expiration timestamp,
        target price, and monitored offers with latest prices.
    """
    try:
        user_id = await resolve_effective_user_id()
    except PermissionError as e:
        return {"status": "error", "error": "unauthorized", "message": str(e)}

    async with async_session_factory() as session:
        try:
            service = TrackingService(session)
            result = await service.get_tracking_status(user_id=user_id, tracker_id=tracker_id)
            await session.commit()
            return {"status": "success", **result}
        except TrackerNotFoundError as tne:
            await session.rollback()
            return {"status": "not_found", "message": str(tne)}
        except Exception as e:
            await session.rollback()
            logger.exception("get_tracking_status failed")
            return {"status": "error", "message": str(e)}


async def list_trackers(status: str | None = None) -> dict[str, Any]:
    """Lists all price trackers created by the user.

    Args:
        status: Optional filter by tracker status ('active', 'stopped', 'expired').

    Returns:
        List of trackers with product title, status, expiration, and tracked offers count.
    """
    try:
        user_id = await resolve_effective_user_id()
    except PermissionError as e:
        return {"status": "error", "error": "unauthorized", "message": str(e)}

    async with async_session_factory() as session:
        try:
            service = TrackingService(session)
            trackers = await service.list_trackers(user_id=user_id)
            await session.commit()
            if status:
                trackers = [t for t in trackers if t["status"] == status]
            return {
                "status": "success",
                "trackers_count": len(trackers),
                "trackers": trackers,
            }
        except Exception as e:
            await session.rollback()
            logger.exception("list_trackers failed")
            return {"status": "error", "message": str(e)}


async def get_price_history(offer_id: str, limit: int = 30) -> dict[str, Any]:
    """Retrieves chronological price check observations for an offer.

    Args:
        offer_id: Unique Offer UUID.
        limit: Max observations to return (default: 30).

    Returns:
        List of historical price checks with timestamps, prices, and availability.
    """
    async with async_session_factory() as session:
        try:
            service = PriceService(session)
            history = await service.get_price_history(offer_id=offer_id, limit=limit)
            await session.commit()
            return {
                "status": "success",
                "offer_id": offer_id,
                "observations_count": len(history),
                "history": history,
            }
        except Exception as e:
            await session.rollback()
            logger.exception("get_price_history failed")
            return {"status": "error", "message": str(e)}


async def compare_quotes(
    vertical: str,
    origin: str | None = None,
    destination: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Compares point-in-time quotes for travel or on-demand services (Section 10B).

    Args:
        vertical: Service vertical (e.g. 'flights', 'rides', 'trains').
        origin: Departure or pickup point.
        destination: Arrival or drop-off point.
        date: Travel or departure date (YYYY-MM-DD).

    Returns:
        Comparison quotes or availability status.
    """
    return {
        "status": "not_implemented",
        "supported": False,
        "vertical": vertical,
        "message": (
            f"Point-in-time quote comparison for vertical '{vertical}' is scheduled for Phase 14 (Flights). "
            "Currently the 'products' vertical is fully active for deal discovery and 14-day tracking."
        ),
    }
