"""Offer model (Current price and availability of a subject at a source)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.observation import Observation
    from app.models.source import Source
    from app.models.subject import Subject
    from app.models.tracker import TrackedOffer


class Offer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An offer represents an observable purchase or booking opportunity at a source."""

    __tablename__ = "offers"

    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    url_or_deeplink: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    # Granular price breakdown
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )  # shipping/convenience
    taxes: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discounts: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Availability & condition
    availability: Mapped[str] = mapped_column(
        String(50), default="unknown", nullable=False
    )  # in_stock, out_of_stock, preorder, unknown
    condition: Mapped[str] = mapped_column(
        String(50), default="new", nullable=False
    )  # new, refurbished, used
    seller: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Match certainty hierarchy
    match_status: Mapped[str] = mapped_column(
        String(50), default="uncertain", nullable=False
    )  # exact, uncertain, mismatch
    matched_on: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # gtin, mpn, sku, brand_model_variant, llm_verified
    match_reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # Price status & check tracking
    price_status: Mapped[str] = mapped_column(
        String(50), default="ok", nullable=False
    )  # ok, unavailable, failed
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Flexible vertical-specific offer attributes
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_id", "url_or_deeplink", name="uq_offers_source_canonical_url"),
        Index("ix_offers_subject_status", "subject_id", "match_status", "availability"),
    )

    # Relationships
    subject: Mapped["Subject"] = relationship("Subject", back_populates="offers")
    source: Mapped["Source"] = relationship("Source", back_populates="offers")
    observations: Mapped[list["Observation"]] = relationship(
        "Observation", back_populates="offer", cascade="all, delete-orphan"
    )
    tracked_in: Mapped[list["TrackedOffer"]] = relationship(
        "TrackedOffer", back_populates="offer", cascade="all, delete-orphan"
    )
