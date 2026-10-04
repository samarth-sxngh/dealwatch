"""API routes for managing notifications and triggering alert dispatch."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import get_current_user_id
from app.database import get_db_session
from app.models.notification import NotificationPreference
from app.services.email_dispatcher import EmailDispatcherService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


class PreferenceUpdateRequest(BaseModel):
    email_enabled: bool


@router.post("/dispatch-pending", summary="Trigger dispatch of pending alert emails")
async def trigger_dispatch_pending(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 50,
) -> dict[str, Any]:
    """Manually or programmatically triggers dispatch of queued alert notifications."""
    try:
        dispatcher = EmailDispatcherService(session)
        summary = await dispatcher.dispatch_pending(limit=limit)
        await session.commit()
        return {"status": "success", "summary": summary}
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to dispatch pending notifications")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/preferences", summary="Get notification preferences for authenticated user")
async def get_notification_preferences(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Returns email notification preferences for the active user."""
    user_id = get_current_user_id()
    if not user_id:
        return {"email_enabled": True, "user_id": None}

    stmt = select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    res = await session.execute(stmt)
    pref = res.scalar_one_or_none()

    return {
        "user_id": str(user_id),
        "email_enabled": pref.email_enabled if pref else True,
    }


@router.put("/preferences", summary="Update notification preferences for authenticated user")
async def update_notification_preferences(
    req: PreferenceUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Updates whether the active user receives email alert notifications."""
    user_id = get_current_user_id()
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to update notification preferences.",
        )

    stmt = select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    res = await session.execute(stmt)
    pref = res.scalar_one_or_none()

    if not pref:
        pref = NotificationPreference(user_id=user_id, email_enabled=req.email_enabled)
        session.add(pref)
    else:
        pref.email_enabled = req.email_enabled

    await session.commit()
    return {
        "status": "success",
        "user_id": str(user_id),
        "email_enabled": pref.email_enabled,
    }
