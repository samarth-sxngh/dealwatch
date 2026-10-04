"""Offer repository for managing observed offers across retailers."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.offer import Offer
from app.repositories.base import BaseRepository


class OfferRepository(BaseRepository[Offer]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Offer)

    async def get_by_source_and_url(self, source_id: uuid.UUID, canonical_url: str) -> Offer | None:
        stmt = (
            select(Offer)
            .options(selectinload(Offer.source))
            .where(Offer.source_id == source_id, Offer.url_or_deeplink == canonical_url)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_offers_for_subject(
        self,
        subject_id: uuid.UUID | str,
        exact_only: bool = False,
    ) -> list[Offer]:
        uid = uuid.UUID(str(subject_id)) if isinstance(subject_id, str) else subject_id
        stmt = select(Offer).options(selectinload(Offer.source)).where(Offer.subject_id == uid)
        if exact_only:
            stmt = stmt.where(Offer.match_status == "exact")

        # Sort verified offers by price ascending (nulls last)
        stmt = stmt.order_by(Offer.total_price.asc().nulls_last())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save_or_update_offer(
        self,
        subject_id: uuid.UUID,
        source_id: uuid.UUID,
        canonical_url: str,
        currency: str,
        base_price: Decimal | None = None,
        fees: Decimal | None = None,
        taxes: Decimal | None = None,
        discounts: Decimal | None = None,
        total_price: Decimal | None = None,
        availability: str = "unknown",
        condition: str = "new",
        seller: str | None = None,
        match_status: str = "uncertain",
        matched_on: str | None = None,
        match_reasons: list[str] | None = None,
        price_status: str = "ok",
        attributes: dict[str, Any] | None = None,
    ) -> Offer:
        offer = await self.get_by_source_and_url(source_id, canonical_url)
        if not offer:
            offer = Offer(
                id=uuid.uuid4(),
                subject_id=subject_id,
                source_id=source_id,
                url_or_deeplink=canonical_url,
                currency=currency.upper(),
                base_price=base_price,
                fees=fees,
                taxes=taxes,
                discounts=discounts,
                total_price=total_price,
                availability=availability,
                condition=condition,
                seller=seller,
                match_status=match_status,
                matched_on=matched_on,
                match_reasons=match_reasons or [],
                price_status=price_status,
                attributes=attributes or {},
                is_active=True,
            )
            self.session.add(offer)
        else:
            # Update latest observed pricing and availability
            offer.currency = currency.upper()
            if price_status == "ok":
                offer.base_price = base_price
                offer.total_price = total_price
                offer.fees = fees
                offer.taxes = taxes
            offer.availability = availability
            offer.condition = condition
            offer.price_status = price_status
            if match_status == "exact":
                offer.match_status = "exact"
                offer.matched_on = matched_on
                offer.match_reasons = match_reasons or []

        await self.session.flush()
        return offer
