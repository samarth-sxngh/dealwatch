"""Source model (Generalizes retailers across verticals)."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.offer import Offer


class Source(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Source entity (retailer, airline, aggregator, booking platform)."""

    __tablename__ = "sources"

    vertical: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True
    )  # ISO 3166-1 alpha-2
    currency: Mapped[str] = mapped_column(String(3), nullable=False)  # ISO 4217
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Access tier (1: API, 2: Permitted Structured Pages, 3: User data, 4: Deep link only)
    access_tier: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    tos_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_limit_per_second: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "vertical", "domain", "country", name="uq_sources_vertical_domain_country"
        ),
        Index("ix_sources_vertical_domain", "vertical", "domain"),
    )

    offers: Mapped[list["Offer"]] = relationship(
        "Offer", back_populates="source", cascade="all, delete-orphan"
    )
