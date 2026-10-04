"""Source repository for managing retail and platform sources."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.repositories.base import BaseRepository


class SourceRepository(BaseRepository[Source]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Source)

    async def get_by_domain_and_country(
        self, domain: str, country: str, vertical: str = "products"
    ) -> Source | None:
        stmt = select(Source).where(
            Source.domain == domain.lower(),
            Source.country == country.upper(),
            Source.vertical == vertical,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        domain: str,
        name: str,
        country: str,
        currency: str,
        vertical: str = "products",
        access_tier: int = 2,
    ) -> Source:
        source = await self.get_by_domain_and_country(domain, country, vertical)
        if source:
            return source

        source = Source(
            id=uuid.uuid4(),
            vertical=vertical,
            name=name,
            country=country.upper(),
            currency=currency.upper(),
            domain=domain.lower(),
            access_tier=access_tier,
            allowed_actions=["fetch_observation", "discover"],
            rate_limit_per_second=0.5,
            is_active=True,
        )
        self.session.add(source)
        await self.session.flush()
        return source
