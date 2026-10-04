"""Subject repository for comparison entities and product details."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.subject import ProductDetails, Subject
from app.repositories.base import BaseRepository


class SubjectRepository(BaseRepository[Subject]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Subject)

    async def get_by_id_with_details(self, subject_id: uuid.UUID | str) -> Subject | None:
        uid = uuid.UUID(str(subject_id)) if isinstance(subject_id, str) else subject_id
        stmt = (
            select(Subject)
            .options(selectinload(Subject.product_details), selectinload(Subject.offers))
            .where(Subject.id == uid)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_normalized_key(self, vertical: str, normalized_key: str) -> Subject | None:
        stmt = (
            select(Subject)
            .options(selectinload(Subject.product_details))
            .where(Subject.vertical == vertical, Subject.normalized_key == normalized_key)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_product_subject(
        self,
        normalized_key: str,
        title: str,
        brand: str | None = None,
        model: str | None = None,
        variant: str | None = None,
        gtin: str | None = None,
        mpn: str | None = None,
        sku: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        raw_specs: dict[str, Any] | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Subject:
        subject = Subject(
            id=uuid.uuid4(),
            vertical="products",
            normalized_key=normalized_key,
            attributes=attributes or {},
            is_active=True,
        )
        self.session.add(subject)
        await self.session.flush()

        details = ProductDetails(
            id=uuid.uuid4(),
            subject_id=subject.id,
            title=title,
            brand=brand,
            model=model,
            variant=variant,
            gtin=gtin,
            mpn=mpn,
            sku=sku,
            description=description,
            image_url=image_url,
            raw_specs=raw_specs or {},
        )
        self.session.add(details)
        await self.session.flush()

        subject.product_details = details
        return subject
