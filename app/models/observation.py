"""Observation model (Immutable point-in-time price check / quote history)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.offer import Offer


class Observation(Base, UUIDPrimaryKeyMixin):
    """Immutable point-in-time observation of an offer (replaces price_history)."""

    __tablename__ = "observations"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    check_run_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    availability: Mapped[str] = mapped_column(String(50), default="unknown", nullable=False)
    price_status: Mapped[str] = mapped_column(
        String(50), default="ok", nullable=False
    )  # ok, unavailable, failed

    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        # Critical rule: unique per (offer_id, check_run_id) so retries never duplicate
        UniqueConstraint("offer_id", "check_run_id", name="uq_observations_offer_check_run"),
        Index("ix_observations_offer_observed", "offer_id", "observed_at"),
    )

    offer: Mapped["Offer"] = relationship("Offer", back_populates="observations")
