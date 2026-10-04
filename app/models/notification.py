"""Notification and Preference models for alert tracking and deduplication."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tracker import Tracker
    from app.models.user import User


class Notification(Base, UUIDPrimaryKeyMixin):
    """Notification record with strict deduplication keys."""

    __tablename__ = "notifications"

    tracker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trackers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Types: price_drop, target_reached, competitor_cheaper, tracking_expired
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Dedup key: e.g. tracker:offer:price_drop:28999:INR:2026-10-02
    deduplication_key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending, sent, failed
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    tracker: Mapped["Tracker"] = relationship("Tracker", back_populates="notifications")


class NotificationPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User notification channel settings."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="notification_preference")
