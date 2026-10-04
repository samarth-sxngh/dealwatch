"""Subject and Vertical Extension Models (Generic Multi-Vertical Core)."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.offer import Offer
    from app.models.tracker import Tracker


class Subject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Generic comparison subject across verticals (Product, Flight, Bus, etc.)."""

    __tablename__ = "subjects"

    vertical: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    normalized_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("vertical", "normalized_key", name="uq_subjects_vertical_normalized_key"),
        Index("ix_subjects_vertical_key", "vertical", "normalized_key"),
    )

    # Extension table relationship for Products
    product_details: Mapped["ProductDetails | None"] = relationship(
        "ProductDetails", back_populates="subject", uselist=False, cascade="all, delete-orphan"
    )

    offers: Mapped[list["Offer"]] = relationship(
        "Offer", back_populates="subject", cascade="all, delete-orphan"
    )
    trackers: Mapped[list["Tracker"]] = relationship(
        "Tracker", back_populates="subject", cascade="all, delete-orphan"
    )


class ProductDetails(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Extension table holding typed product-specific fields for Vertical #1."""

    __tablename__ = "product_details"

    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    gtin: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)  # UPC/EAN/ISBN
    mpn: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )  # Manufacturer Part Number
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    raw_specs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationship back to generic subject
    subject: Mapped[Subject] = relationship("Subject", back_populates="product_details")
