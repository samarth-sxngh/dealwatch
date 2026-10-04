"""Price service for recording price checks and querying price history."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.observation import Observation
from app.repositories.observation_repository import ObservationRepository
from app.repositories.offer_repository import OfferRepository


class PriceService:
    """Service managing price checks, history retrieval, and price integrity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.offer_repo = OfferRepository(session)
        self.observation_repo = ObservationRepository(session)

    async def record_check_result(
        self,
        offer_id: uuid.UUID | str,
        check_run_id: str,
        currency: str,
        base_price: Decimal | None = None,
        total_price: Decimal | None = None,
        fees: Decimal | None = None,
        taxes: Decimal | None = None,
        availability: str = "unknown",
        price_status: str = "ok",
        raw_data: dict[str, Any] | None = None,
    ) -> Observation:
        """Records an observation and updates offer.

        Failed checks NEVER overwrite previously recorded valid prices.
        """
        oid = uuid.UUID(str(offer_id)) if isinstance(offer_id, str) else offer_id
        offer = await self.offer_repo.get_by_id(oid)
        if not offer:
            raise ValueError(f"Offer '{offer_id}' not found.")

        # 1. Record immutable point-in-time observation
        obs = await self.observation_repo.record_observation(
            offer_id=offer.id,
            check_run_id=check_run_id,
            currency=currency,
            base_price=base_price,
            fees=fees,
            taxes=taxes,
            total_price=total_price,
            availability=availability,
            price_status=price_status,
            raw_data=raw_data,
        )

        # 2. Update offer latest state ONLY if price check succeeded or status is ok
        if price_status == "ok":
            offer.currency = currency.upper()
            offer.base_price = base_price
            offer.total_price = total_price
            offer.fees = fees
            offer.taxes = taxes
            offer.availability = availability
            offer.price_status = "ok"
        else:
            # Mark check failed/unavailable on offer without destroying historical price
            offer.price_status = price_status

        await self.session.flush()
        return obs

    async def get_price_history(
        self, offer_id: uuid.UUID | str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Returns chronological price check history for an offer."""
        oid = uuid.UUID(str(offer_id)) if isinstance(offer_id, str) else offer_id
        observations = await self.observation_repo.get_for_offer(oid, limit=limit)

        return [
            {
                "observation_id": str(o.id),
                "check_run_id": o.check_run_id,
                "currency": o.currency,
                "total_price": float(o.total_price) if o.total_price is not None else None,
                "base_price": float(o.base_price) if o.base_price is not None else None,
                "availability": o.availability,
                "price_status": o.price_status,
                "observed_at": o.observed_at.isoformat(),
            }
            for o in observations
        ]
