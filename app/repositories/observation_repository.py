"""Observation repository for immutable point-in-time check observations."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.observation import Observation
from app.repositories.base import BaseRepository


class ObservationRepository(BaseRepository[Observation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Observation)

    async def get_for_offer(self, offer_id: uuid.UUID | str, limit: int = 50) -> list[Observation]:
        uid = uuid.UUID(str(offer_id)) if isinstance(offer_id, str) else offer_id
        stmt = (
            select(Observation)
            .where(Observation.offer_id == uid)
            .order_by(Observation.observed_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def record_observation(
        self,
        offer_id: uuid.UUID,
        check_run_id: str,
        currency: str,
        base_price: Decimal | None = None,
        fees: Decimal | None = None,
        taxes: Decimal | None = None,
        total_price: Decimal | None = None,
        availability: str = "unknown",
        price_status: str = "ok",
        raw_data: dict[str, Any] | None = None,
    ) -> Observation:
        """Records an immutable price check.

        Uses ON CONFLICT DO NOTHING on (offer_id, check_run_id) so retries are safe.
        """
        obs_id = uuid.uuid4()
        now = datetime.now(UTC)
        stmt = (
            insert(Observation)
            .values(
                id=obs_id,
                offer_id=offer_id,
                check_run_id=check_run_id,
                currency=currency.upper(),
                base_price=base_price,
                fees=fees,
                taxes=taxes,
                total_price=total_price,
                availability=availability,
                price_status=price_status,
                raw_data=raw_data or {},
                observed_at=now,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["offer_id", "check_run_id"])
        )
        await self.session.execute(stmt)
        await self.session.flush()

        # Fetch the resulting observation (newly created or existing)
        fetch_stmt = select(Observation).where(
            Observation.offer_id == offer_id,
            Observation.check_run_id == check_run_id,
        )
        result = await self.session.execute(fetch_stmt)
        return result.scalar_one()
