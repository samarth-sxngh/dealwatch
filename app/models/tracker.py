"""Tracker models for managing active 14-day price tracking jobs."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.notification import Notification
    from app.models.offer import Offer
    from app.models.subject import Subject
    from app.models.user import User


class Tracker(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User tracking job for a specific subject and its offers."""

    __tablename__ = "trackers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )  # active, stopped, expired
    duration_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    check_interval_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)

    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    price_drop_alert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        Index("ix_trackers_status_expires", "status", "expires_at"),
        Index("ix_trackers_user_status", "user_id", "status"),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="trackers")
    subject: Mapped["Subject"] = relationship("Subject", back_populates="trackers")
    tracked_offers: Mapped[list["TrackedOffer"]] = relationship(
        "TrackedOffer", back_populates="tracker", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="tracker", cascade="all, delete-orphan"
    )


class TrackedOffer(Base, UUIDPrimaryKeyMixin):
    """Associates a tracker with specific verified offers being monitored."""

    __tablename__ = "tracked_offers"

    tracker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trackers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_original: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tracker_id", "offer_id", name="uq_tracked_offers_tracker_offer"),
    )

    tracker: Mapped["Tracker"] = relationship("Tracker", back_populates="tracked_offers")
    offer: Mapped["Offer"] = relationship("Offer", back_populates="tracked_in")
